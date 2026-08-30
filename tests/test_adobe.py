"""
Prototype: Adobe PDF Extract API for Lloyd's syndicate reports.

Extracts text, tables, and figures from a scanned syndicate report PDF
and saves structured output into a report-specific subfolder.

Usage:
    python test_adobe.py

Requires environment variables:
    PDF_SERVICES_CLIENT_ID
    PDF_SERVICES_CLIENT_SECRET
"""

import os
import json
import zipfile
import logging
from pathlib import Path

import pytest

# Optional paid-integration dependency: skip cleanly rather than fail
# collection when it is not installed. This is a manual integration
# script first and a pytest-collected file second.
pytest.importorskip("adobe.pdfservices", reason="optional Adobe PDF Services SDK not installed")

from dotenv import load_dotenv

from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.pdfjobs.jobs.extract_pdf_job import ExtractPDFJob
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_pdf_params import ExtractPDFParams
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_element_type import ExtractElementType
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.extract_renditions_element_type import ExtractRenditionsElementType
from adobe.pdfservices.operation.pdfjobs.params.extract_pdf.table_structure_type import TableStructureType
from adobe.pdfservices.operation.pdfjobs.result.extract_pdf_result import ExtractPDFResult
from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
from adobe.pdfservices.operation.io.stream_asset import StreamAsset
from adobe.pdfservices.operation.exception.exceptions import (
    ServiceApiException,
    ServiceUsageException,
    SdkException,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()


def extract_lloyds_report(pdf_path: Path, output_root: Path) -> Path:
    """Extract text, tables, and figures from a Lloyd's syndicate report PDF.

    Args:
        pdf_path: Path to the input PDF file.
        output_root: Root directory for extraction output.

    Returns:
        Path to the report-specific output directory.
    """
    report_name = pdf_path.stem
    report_out_dir = output_root / report_name
    report_out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Authenticate
    client_id = os.getenv("PDF_SERVICES_CLIENT_ID")
    client_secret = os.getenv("PDF_SERVICES_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(
            "Missing PDF_SERVICES_CLIENT_ID and/or PDF_SERVICES_CLIENT_SECRET "
            "environment variables. Set them in .env or your shell."
        )

    credentials = ServicePrincipalCredentials(
        client_id=client_id,
        client_secret=client_secret,
    )
    pdf_services = PDFServices(credentials=credentials)
    logger.info("Authenticated with Adobe PDF Services")

    # 2. Upload PDF
    logger.info(f"Uploading {pdf_path} ({pdf_path.stat().st_size / 1024:.0f} KB)")
    with open(pdf_path, "rb") as f:
        input_stream = f.read()

    input_asset = pdf_services.upload(
        input_stream=input_stream,
        mime_type=PDFServicesMediaType.PDF,
    )
    logger.info("Upload complete")

    # 3. Configure extraction parameters
    #    - elements_to_extract: TEXT + TABLES (structural JSON)
    #    - elements_to_extract_renditions: TABLES (XLSX) + FIGURES (PNG)
    #    - table_structure_type: XLSX for downstream pandas processing
    extract_params = ExtractPDFParams(
        elements_to_extract=[ExtractElementType.TEXT, ExtractElementType.TABLES],
        elements_to_extract_renditions=[
            ExtractRenditionsElementType.TABLES,
            ExtractRenditionsElementType.FIGURES,
        ],
        table_structure_type=TableStructureType.XLSX,
    )

    # 4. Submit Extract job
    extract_job = ExtractPDFJob(
        input_asset=input_asset,
        extract_pdf_params=extract_params,
    )
    logger.info("Submitting Extract PDF job...")
    location = pdf_services.submit(extract_job)
    logger.info("Job submitted, waiting for completion...")

    # 5. Poll for result
    response = pdf_services.get_job_result(location, ExtractPDFResult)
    extract_result: ExtractPDFResult = response.get_result()
    logger.info("Job complete")

    # 5a. Download the ZIP resource (contains structuredData.json, tables, figures)
    result_asset: CloudAsset = extract_result.get_resource()
    stream_asset: StreamAsset = pdf_services.get_content(result_asset)

    zip_path = report_out_dir / "extractResult.zip"
    with open(zip_path, "wb") as f:
        f.write(stream_asset.get_input_stream())
    logger.info(f"Downloaded result ZIP ({zip_path.stat().st_size / 1024:.0f} KB)")

    # 6. Unzip into report subfolder
    with zipfile.ZipFile(zip_path, "r") as zf:
        extracted_files = zf.namelist()
        zf.extractall(report_out_dir)
    logger.info(f"Extracted {len(extracted_files)} files into {report_out_dir}")

    # Clean up ZIP
    zip_path.unlink()
    logger.info(f"Removed temporary ZIP")

    # Summary
    tables_dir = report_out_dir / "tables"
    figures_dir = report_out_dir / "figures"
    n_tables = len(list(tables_dir.glob("*"))) if tables_dir.exists() else 0
    n_figures = len(list(figures_dir.glob("*"))) if figures_dir.exists() else 0

    logger.info(
        f"Extraction complete for {report_name}: "
        f"JSON={'yes' if (report_out_dir / 'structuredData.json').exists() else 'no'}, "
        f"tables={n_tables}, figures={n_figures}"
    )

    return report_out_dir


if __name__ == "__main__":
    input_pdf = Path("syndicate_reports/pdfs/syndicate_2987_2018.pdf")
    output_root = Path("pdf_extraction/adobe_output")

    if not input_pdf.exists():
        logger.error(f"Input PDF not found: {input_pdf}")
        raise SystemExit(1)

    try:
        result_dir = extract_lloyds_report(input_pdf, output_root)
        logger.info(f"Output directory: {result_dir}")
    except (ServiceApiException, ServiceUsageException, SdkException) as e:
        logger.error(f"Adobe PDF Extract error: {e}")
        raise SystemExit(1)
    except ValueError as e:
        logger.error(str(e))
        raise SystemExit(1)
