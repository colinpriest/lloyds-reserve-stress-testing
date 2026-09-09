"""Round 54 (review finding M13): the RITC scanner decides by direction and effective
year, not by pattern class.

The frozen scan flagged 1861/2020 on a £273m premium PAYABLE by the syndicate under a
contract agreed in February 2021 (outgoing and prospective), and 2003/2015 on the
closure of its own 2013 and prior years into its own 2014 year (internal); it flagged
an accounting policy (5151) and an illustrative-share results table (3902, 4020) as
occurrences; and it flagged 1084/2020 on an acceptance "effective 1 January 2021".
The 1861/2020 report does carry an acceptance: at 31 December 2019 its 2018 year of
account accepted the RITC of Syndicates 5820 and 1206, effective for 2020.

Run:  python -m pytest tests/test_ritc_scanner.py -q
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ritc_scanner as rs  # noqa: E402


def cls(sentence, own="1861", year=2020):
    return rs.classify_sentence(sentence, own, year)


class TestDirection:
    def test_premium_payable_under_a_contract_agreed_next_year_is_outward_and_next_year(self):
        e = cls("The 2018 year of account has closed externally into the 2021 year of account of "
                "Premia Managing Agency Limited's Syndicate 1884. The contract was agreed on 18th "
                "February 2021 with a net reinsurance to close premium payable by the Syndicate of "
                "£273.0m.")
        assert e["direction"] == "outward"
        assert e["event_year"] == 2021

    def test_acceptance_at_31_december_is_inward_and_effective_the_next_year(self):
        e = cls("At 31 December 2019 the 2018 YOA of the Syndicate accepted the RITC of the 2017 "
                "years of account of Syndicates 5820 and 1206, two other Syndicates managed by "
                "Canopius Managing Agents Limited.")
        assert e["direction"] == "inward"
        assert e["event_year"] == 2020
        assert e["counterparty"] == "5820"

    def test_closure_into_own_year_is_internal(self):
        e = cls("The 2013 and prior years of account have Reinsured to Close (\"RITC\") into the "
                "syndicate's 2014 year of account for an RITC premium of $2,043m.", own="2003", year=2015)
        assert e["direction"] == "internal"

    def test_closure_into_another_syndicate_is_outward(self):
        e = cls("As from 1 January 2018, it will be closed by Reinsurance to Close (\"RITC\") into "
                "Syndicate 2003.", own="1209", year=2017)
        assert e["direction"] == "outward"
        assert e["event_year"] == 2018

    def test_acceptance_effective_next_year_is_inward_next_year(self):
        e = cls("Effective 1 January 2021, the Syndicate accepted the reinsurance to close (RITC) of "
                "the liabilities of AXA Special Purpose Arrangement Syndicate 6130 for the 2018 Year "
                "of Account.", own="1084", year=2020)
        assert e["direction"] == "inward"
        assert e["event_year"] == 2021

    def test_acceptance_with_effect_from_january_of_the_report_year(self):
        e = cls("With effect from 1 January 2019, Syndicate 2488 accepted the reinsurance to close of "
                "the liabilities of Syndicate 1882.", own="2488", year=2019)
        assert e["direction"] == "inward" and e["event_year"] == 2019

    def test_take_on_balance_is_inward_in_the_report_year(self):
        e = cls("Change in prior year provisions 597,491 409 RITC take on balance (501,578) (959,584) "
                "Claims incurred, net of reinsurance 95,913", own="2008", year=2019)
        assert e["direction"] == "inward" and e["event_year"] == 2019

    def test_acquisition_by_ritc_is_inward(self):
        e = cls("The Syndicate entered into a Reinsurance to Close (RITC) agreement to acquire the "
                "run-off UK motor division of Chaucer Syndicate 1084.", own="1274", year=2018)
        assert e["direction"] == "inward"

    def test_an_intention_without_a_date_has_no_year(self):
        e = cls("It is the intention that the 2019 and 2020 years of account will close by "
                "reinsurance to close into syndicate 3500 at their natural close.", own="2468", year=2020)
        assert e["prospective"] and e["event_year"] is None

    def test_reinsured_to_close_by_another_syndicate_is_outward(self):
        e = cls("The 2020 and prior years of account have been reinsured to close by Syndicate 3500 "
                "managed by Riverstone Managing Agency Ltd.", own="1200", year=2022)
        assert e["direction"] == "outward"


def _report(*pages):
    return list(pages)


class TestDecision:
    def _scan(self, monkeypatch, pages, name):
        monkeypatch.setattr(rs, "load_page_texts", lambda p: pages)
        return rs.scan_report(Path(name))

    def test_1861_2020_is_flagged_on_the_accepted_transfer_not_the_payable_premium(self, monkeypatch):
        pages = _report(
            "Report of the Directors\nThe 2018 year of account in turn has closed externally into the "
            "2021 year of account of Premia Managing Agency Limited's Syndicate 1884 effective 1 January "
            "2021 following the completion of a reinsurance to close agreement on 18 February 2021.",
            "Notes to the Financial Statements\n13. Claims\nThe reconciliation of opening and closing "
            "provision for claims is as follows: RITC adjustment 63,393 14,625. 1 2020 RITC adjustment: "
            "At 31 December 2019 the 2018 YOA of the Syndicate accepted the RITC of the 2017 years of "
            "account of Syndicates 5820 and 1206, two other Syndicates managed by Canopius Managing "
            "Agents Limited. This was recorded as a balance sheet transaction.",
            "Post balance sheet events\nThe contract was agreed on 18th February 2021 with a net "
            "reinsurance to close premium payable by the Syndicate of £273.0m.")
        r = self._scan(monkeypatch, pages, "syndicate_1861_2020.pdf")
        assert r["ritc_occurred"] is True
        assert r["direction"] == "inward" and r["event_year"] == 2020
        assert "accepted the RITC" in r["evidence"]
        assert "273.0m" not in r["evidence"]

    def test_2003_2015_own_year_closure_is_not_flagged(self, monkeypatch):
        pages = _report("Future developments\nThe 2013 and prior years of account have Reinsured to "
                        "Close (\"RITC\") into the syndicate's 2014 year of account for an RITC premium "
                        "of $2,043m. The syndicate purchases a Whole Account Stop Loss reinsurance.")
        r = self._scan(monkeypatch, pages, "syndicate_2003_2015.pdf")
        assert r["ritc_occurred"] is False
        assert r["events"][0]["direction"] == "internal"

    def test_accounting_policy_boilerplate_is_not_flagged(self, monkeypatch):
        pages = _report("Accounting policies\nReinsurance to close\nA year of account is normally closed "
                        "by reinsurance into the following year of account. The amount of the RITC "
                        "premium is determined by the managing agent, generally by estimating the cost "
                        "of claims notified but not settled.")
        r = self._scan(monkeypatch, pages, "syndicate_5151_2018.pdf")
        assert r["ritc_occurred"] is False

    def test_illustrative_share_table_is_not_flagged(self, monkeypatch):
        pages = _report("Results for illustrative share of £10,000\nGross premiums written 7,646 5,979 "
                        "Net premiums 4,992 4,157 RITC from an earlier year of account 975 - Net claims "
                        "(2,861) (2,654) Reinsurance to close (1,065) (996)")
        r = self._scan(monkeypatch, pages, "syndicate_3902_2020.pdf")
        assert r["ritc_occurred"] is False

    def test_an_acceptance_effective_next_year_flags_next_year_by_propagation(self, monkeypatch):
        pages = _report("Effective 1 January 2021, the Syndicate accepted the reinsurance to close "
                        "(RITC) of the liabilities of Syndicate 6130 for the 2018 Year of Account.")
        r20 = self._scan(monkeypatch, pages, "syndicate_1084_2020.pdf")
        assert r20["ritc_occurred"] is False
        results = {"1084_2020": r20,
                   "1084_2021": {"detection": "successful", "ritc_occurred": False, "events": [],
                                 "confidence": "strong", "evidence": "no RITC reference in report",
                                 "section": "whole document scan", "page": None}}
        n = rs.propagate(results)
        assert n == 1
        assert results["1084_2021"]["ritc_occurred"] is True
        assert results["1084_2021"]["evidence_report"] == "1084_2020"
        assert results["1084_2021"]["event_year"] == 2021

    def test_outward_only_report_records_why_it_is_clean(self, monkeypatch):
        pages = _report("The 2020 and prior years of account have been reinsured to close by Syndicate "
                        "3500 managed by Riverstone Managing Agency Ltd. As a result liabilities "
                        "totalling £273.0m have transferred.")
        r = self._scan(monkeypatch, pages, "syndicate_1200_2022.pdf")
        assert r["ritc_occurred"] is False
        assert "outgoing" in r["evidence"]


class TestSecondPass:
    """Rules from the first corpus rescan's diff."""

    def test_premium_received_from_earlier_years_is_internal(self):
        e = cls("Reinsurance to close premium received from earlier years of account, net of "
                "reinsurance 12,237", own="33", year=2015)
        assert e["direction"] == "internal"

    def test_liabilities_assumed_by_another_syndicate_is_outward(self):
        e = cls("The 2018 year of account has been closed by means of a split RITC, whereby "
                "liabilities relating to the 2017 and prior years of account have been assumed by "
                "Syndicate 1994.", own="1969", year=2020)
        assert e["direction"] == "outward"

    def test_a_generic_accepted_via_ritc_line_flags_nothing(self):
        e = cls("There is some modest residual run-off exposure (accepted via the Reinsurance to "
                "Close) although the reserves and notifications are at a satisfactory level.",
                own="1176", year=2016)
        assert e["direction"] != "inward"

    def test_a_receiving_year_of_account_dates_the_event(self):
        e = cls("The claims development tables include the historical development of Syndicate 807 "
                "which was reinsured to close into the 2012 year of account of Syndicate 510.",
                own="510", year=2019)
        assert e["direction"] == "inward"
        assert e["event_year"] == 2014 and e["dated"] == "yoa"

    def test_another_syndicate_closing_into_this_one_is_inward(self):
        e = cls("The 2020 and prior years of account of Syndicate 6133 have been reinsured to close "
                "into the syndicate.", own="1969", year=2022)
        assert e["direction"] == "inward" and e["counterparty"] == "6133"

    def test_a_dated_intention_does_not_flag(self, monkeypatch):
        pages = ["SPA 6131 was placed into run off at the end of 2021 and, when the 2021 YOA closes "
                 "at the end of 2023, it is the intention to RITC into Syndicate 1729."]
        monkeypatch.setattr(rs, "load_page_texts", lambda p: pages)
        r = rs.scan_report(Path("syndicate_1729_2022.pdf"))
        results = {"1729_2022": r, "1729_2023": {"detection": "successful", "ritc_occurred": False,
                   "events": [], "confidence": "strong", "evidence": "x", "section": "s", "page": None}}
        assert rs.propagate(results) == 0

    def test_undated_sentence_inherits_the_year_of_the_dated_one(self, monkeypatch):
        pages = ["It was agreed by the Board of the Managing Agency on 6 February 2014, that "
                 "Syndicate 1318 and Syndicate 2318, would pay a reinsurance to close premium to "
                 "Syndicate 318 in respect of the 2011 year of account. The reinsurance to close "
                 "premium received in respect of Syndicate 1318 was £2,579,932."]
        monkeypatch.setattr(rs, "load_page_texts", lambda p: pages)
        r15 = rs.scan_report(Path("syndicate_318_2015.pdf"))
        assert r15["ritc_occurred"] is False
        assert all(e["event_year"] == 2014 for e in r15["events"] if e["direction"] == "inward")
        r14 = rs.scan_report(Path("syndicate_318_2014.pdf"))
        assert r14["ritc_occurred"] is True


class TestThirdPass:
    def test_a_managing_agents_disclosure_about_other_syndicates_is_third_party(self):
        e = cls("On 10 February 2022, Asta reinsured to close Syndicate 1980 into Riverstone "
                "Syndicate 3500. On 22 March 2022, Asta took on the management of Syndicate 1922.",
                own="1796", year=2022)
        assert e["direction"] == "third_party"

    def test_took_on_the_management_is_not_a_take_on(self):
        e = cls("On 1 January 2022, Asta took on the management of Syndicate in a Box 1902.",
                own="1796", year=2022)
        assert e["direction"] != "inward"

    def test_a_negated_sentence_flags_nothing(self):
        e = cls("Syndicate 6134 does not participate in the underwriting of any prior year of "
                "Syndicate 2121 and no element of that syndicate's reinsurance to close is borne.",
                own="6134", year=2018)
        assert e["direction"] == "negated"

    def test_a_bare_fragment_naming_a_counterparty_is_not_inward(self):
        e = cls("The RITC of Syndicate 1861 2008 and prior years of account.", own="2255", year=2015)
        assert e["direction"] != "inward"

    def test_an_explicit_acceptance_is_still_inward(self):
        e = cls("At 1 January 2015, Syndicate 2791 accepted a Reinsurance to Close Premium from "
                "Syndicate 6103.", own="2791", year=2015)
        assert e["direction"] == "inward" and e["event_year"] == 2015


class TestFifthPass:
    def test_it_accepted_is_a_self_reference(self):
        e = cls("It accepted the Reinsurance to Close contract of Syndicate 1208 into its 2012 "
                "year of account and Syndicate 102 into its 2014 year of account.", own="3330", year=2014)
        assert e["direction"] == "inward"
        assert e["event_year"] == 2014 and e["dated"] == "yoa"

    def test_a_year_of_account_accepting_is_this_syndicate(self):
        e = cls("On 1 January 2017, the 2017 year of account accepted the RITC of the 2014 year of "
                "account which consisted of the 2007 year of account of Syndicate 1208 and Syndicate "
                "102.", own="3330", year=2017)
        assert e["direction"] == "inward" and e["event_year"] == 2017

    def test_took_on_management_of_a_syndicate_is_not_an_acceptance(self):
        e = cls("On 10 February 2022, Asta took on management of Syndicate in a Box 2880.",
                own="1796", year=2022)
        assert e["direction"] != "inward"

    def test_a_transfer_to_this_syndicate_of_provisions_is_inward(self):
        e = cls("This transaction results in the transfer to Syndicate 3500 of gross and net "
                "technical provisions of $17.6 million and $17.3 million respectively.",
                own="3500", year=2021)
        assert e["direction"] == "inward"


class TestSixthPass:
    def test_an_undated_inward_sentence_inherits_the_reports_dated_acceptance_year(self, monkeypatch):
        pages = ["Effective 1 January 2021, the Syndicate accepted the reinsurance to close (RITC) of "
                 "the liabilities of Syndicate 6130 for the 2018 Year of Account. The RITC premium "
                 "charged was $22.5m, and the transaction resulted in the transfer to the Syndicate of "
                 "gross and net technical provisions, including deferred acquisition costs."]
        monkeypatch.setattr(rs, "load_page_texts", lambda p: pages)
        r = rs.scan_report(Path("syndicate_1084_2020.pdf"))
        assert r["ritc_occurred"] is False
        assert all(e["event_year"] == 2021 for e in r["events"] if e["direction"] == "inward")


class TestSeventhPass:
    def test_a_page_header_date_is_not_an_event_date(self):
        e = cls("Notes to the Financial Statements for the year ended 31 December 2020 The "
                "reconciliation of opening and closing provision for claims is as follows: RITC "
                "adjustment1,2 63,393 14,625 Adjusted 1 January 520,039", own="1861", year=2020)
        assert e["event_year"] != 2021

    def test_closing_own_years_by_an_external_ritc_is_outward(self):
        e = cls("At 31 December 2018 the 2016 & Prior years of account closed by way of an external "
                "reinsurance to close agreement.", own="1861", year=2020)
        assert e["direction"] == "outward"


class TestEighthPass:
    def test_as_at_is_an_event_date(self):
        e = cls("Syndicate 3330 2017 YOA was accepted as an RITC as at 1 January 2020 with £11.8m "
                "of net claims transferred to Syndicate 1110 2019 YOA.", own="1110", year=2021)
        assert e["direction"] == "inward" and e["event_year"] == 2020 and e["dated"] is True

    def test_a_running_header_date_is_not_an_event_date(self):
        e = cls("CMA Syndicate 1861 Annual Report & Accounts 31 December 2020 Page 42 of 44 The "
                "reconciliation of opening and closing provision for claims is as follows: RITC "
                "adjustment1,2 63,393 14,625", own="1861", year=2020)
        assert e["event_year"] != 2021
