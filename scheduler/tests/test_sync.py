import os
import tempfile
import unittest

from schedulermp.bundle import Bundle
from schedulermp.compare import chain_owner_canonical, diff_maps, drc_canonical, generating_canonical, owner_canonical
from schedulermp.config import Settings
from schedulermp.http_client import ApiError, is_duplicate
from schedulermp.mapping import chain_action, drc_body, generating_body, owner_body, valid_flg
from schedulermp.phase1 import verify_certificate, verifications_csv
from schedulermp.pipeline import SyncService
from schedulermp.store import StateStore


TDR_DRC = {
    "status": "success",
    "data": [
        {
            "certificate_details": [
                {
                    "application_id": "TDR202471184557197",
                    "rid": 37,
                    "owner_id": 101,
                    "land_plot_id": 171,
                    "drc_receipt_no": "01",
                    "drc_file_no": "E81UB09Sep2026",
                    "flg": "FIRST_OWNER",
                    "owner_samagra": "321953588",
                    "drc_certificate_no": "DRC/2024/00002/Indore",
                    "owner_from": 101,
                    "owner_to": 101,
                    "actual_value_tdr": 75.92,
                    "trn_value_tdr": 0,
                    "remaining_value_tdr": 75.92,
                }
            ],
            "owner_details": [
                {
                    "owner_id": 101,
                    "land_plot_id": 171,
                    "rid": 37,
                    "owner_type": "Plot",
                    "ownernm": "Ashok Rathore",
                    "owner_samagra": "321953588",
                    "owner_mob": "9827075232",
                }
            ],
            "project_details": [
                {
                    "application_id": "TDR202471184557197",
                    "rid": 37,
                    "implementation_agency": "Indore Municipal Corporation",
                    "project_name": "Mhow Naka to Tori Corner",
                }
            ],
            "land_or_plot_details": [
                {
                    "rid": 37,
                    "plot_id": 171,
                    "plot_no": "55/1",
                    "teh_cd": "03543",
                    "vill_cd": "951464",
                    "colony_name": "lodhipura",
                    "registry_area": 37.96,
                    "proposed_area": 37.96,
                    "ownership": "owner",
                    "value_tdr": 75.92,
                    "land_use": "Transportation",
                }
            ],
        }
    ],
}

GENERATING = {
    "status": "success",
    "data": [
        {
            "generatingarea": [
                {
                    "p_application_id": "TDR202471184557197",
                    "p_rid": 37,
                    "p_implementation_agency": "Indore Municipal Corporation",
                    "p_project_name": "Mhow Naka to Tori Corner",
                    "p_district": "Indore",
                    "p_town_city": "Indore",
                    "p_project_location": "Under municipal area",
                },
                {
                    "p_application_id": "TDR202471184557197",
                    "p_project_name": "Mhow Naka to Tori Corner",
                    "p_implementation_agency": "Indore Municipal Corporation",
                    "p_project_location": "Outside municipal area",
                },
            ],
            "plotRecords": [
                {
                    "rid": 37,
                    "plot_id": 171,
                    "plot_no": "55/1",
                    "teh_cd": "03543",
                    "proposed_area": 37.96,
                    "registry_area": 37.96,
                    "land_use": "Transportation",
                }
            ],
        }
    ],
}


class FakeTdr:
    def __init__(self):
        self.calls = []

    def certificate_numbers(self):
        return ["DRC/2024/00002/Indore"]

    def drc_by_certificate(self, certificate_no):
        self.calls.append(("drc", certificate_no))
        return TDR_DRC

    def application_list(self):
        return [{"application_id": "TDR202471184557197", "rid": 37}]

    def application_detail(self, application_id):
        raise ApiError(404, "not found", {"error": "not found"}, False)

    def owner_by_id(self, owner_id):
        raise ApiError(404, "not found", {"error": "not found"}, False)

    def generating_by_application(self, application_id):
        self.calls.append(("generating", application_id))
        return GENERATING

    def owner_by_certificate(self, certificate_no):
        return TDR_DRC


class FakeChain:
    def __init__(self, drc=None, mismatch=False):
        self.writes = []
        self.mismatch = mismatch
        self.drc = drc

    def get(self, path, params=None):
        params = params or {}
        if path.endswith("/Agency/GetDRCDetails"):
            if self.drc is None and not self.writes:
                return 400, {"error": "certificate not found"}
            data = dict(self.drc or {})
            if self.mismatch:
                data["remaining_value_tdr"] = 1
            return 200, {"success": True, "data": data}
        if path.endswith("/Agency/GetApplicationDetails"):
            return 200, {
                "success": True,
                "data": {
                    "applicationid": params.get("applicationid"),
                    "project_name": "Mhow Naka to Tori Corner",
                    "agency_name": "Indore Municipal Corporation",
                },
            }
        if path.endswith("/Agency/GetOwnerDetails"):
            return 200, {
                "success": True,
                "data": {
                    "applicationid": params.get("applicationid"),
                    "owner_id": params.get("owner_id"),
                    "owner": {
                        "owner_id": params.get("owner_id"),
                        "name": "Ashok Rathore",
                        "samagraID": "321953588",
                        "mobile": "9827075232",
                    },
                },
            }
        return 404, {"error": "not found"}

    def post(self, path, body):
        self.writes.append((path, body))
        if path.endswith("/Department/DRCUpload"):
            self.drc = body
        return {"transactionId": "tx-" + path.rsplit("/", 1)[-1]}


def settings(path: str, dry_run: bool = False) -> Settings:
    return Settings(
        tdr_base_url="http://tdr.local",
        tdr_api_key="",
        tdr_auth_header="Authorization",
        blockchain_base_url="http://chain.local",
        blockchain_api_key="k",
        channel="mptdr",
        org="mpgovdepartment",
        peer="peer0-mpgovdepartment",
        callback_url="",
        state_path=path,
        http_host="127.0.0.1",
        http_port=8088,
        scheduler_api_key="",
        admin_username="admin",
        admin_password="admin",
        phase1_enabled=False,
        phase1_interval_sec=86400,
        phase1_concurrency=2,
        phase2_enabled=False,
        phase2_interval_sec=86400,
        phase2_scan_certs=True,
        phase3_enabled=False,
        phase3_interval_sec=300,
        phase3_scan_certs=False,
        dry_run=dry_run,
        http_timeout_sec=5,
        max_retries=5,
        changed_by="test",
    )


class MappingTests(unittest.TestCase):
    def test_drc_names_and_numbers_normalize(self):
        body = drc_body(TDR_DRC["data"][0]["certificate_details"][0])
        self.assertEqual(body["certificate_no"], "DRC/2024/00002/Indore")
        self.assertEqual(body["flg"], "FIRST_OWNER")
        self.assertTrue(valid_flg(body["flg"]))
        self.assertEqual(chain_action("TRANSFER_OWNER"), "update")
        self.assertEqual(chain_action("UTILIZATION_OWNER"), "update")
        self.assertEqual(chain_action("FIRST_OWNER"), "generate")
        self.assertEqual(chain_action("TRANSFEREE_OWNER"), "generate")
        chain = dict(body)
        chain["certificateNumber"] = chain.pop("certificate_no")
        chain["applicationID"] = chain.pop("applicationid")
        self.assertEqual(diff_maps(drc_canonical(body), drc_canonical(chain)), [])

    def test_owner_type_and_generating_payload(self):
        bundle = Bundle("TDR202471184557197")
        bundle.absorb(GENERATING)
        bundle.absorb(TDR_DRC)
        body = generating_body(bundle.generating, bundle.plots, bundle.lands)
        self.assertEqual(body["p_application_id"], "TDR202471184557197")
        self.assertIn("Outside municipal area", body["p_project_location"])
        self.assertEqual(body["plotRecords"][0]["plot_id"], "171")
        self.assertTrue(body["plotRecords"][0]["plot_id"])
        owner = owner_body(bundle.owners[0], bundle.application_id, bundle.docs)
        self.assertEqual(owner["owner_type"], "PLOT")
        self.assertEqual(owner["applicationid"], "TDR202471184557197")
        self.assertEqual(
            generating_canonical(body)["project_name"],
            "Mhow Naka to Tori Corner",
        )

    def test_owner_read_envelope_uses_application_id(self):
        expected = owner_canonical(
            {
                "applicationid": "TDR202471184557197",
                "owner_id": 101,
                "ownernm": "Ashok Rathore",
                "owner_samagra": "321953588",
                "owner_mob": "9827075232",
            }
        )
        actual = chain_owner_canonical(
            {
                "success": True,
                "data": {
                    "ownerID": "101",
                    "applicationID": "TDR202471184557197",
                    "name": "Ashok Rathore",
                    "samagraID": "321953588",
                    "mobile": "9827075232",
                },
            }
        )
        self.assertEqual(diff_maps(expected, actual), [])

    def test_application_detail_nests_drc_on_owner(self):
        bundle = Bundle("APP-1")
        bundle.absorb(
            {
                "data": [
                    {
                        "owners": [
                            {
                                "owner_id": 101,
                                "ownernm": "Ashok Rathore",
                                "drc_upload": [
                                    {
                                        "drc_certificate_no": "DRC/2024/00002/Indore",
                                        "owner_id": 101,
                                        "flg": "FIRST_OWNER",
                                    }
                                ],
                                "transfer": [],
                            }
                        ]
                    }
                ]
            }
        )
        self.assertEqual(len(bundle.drcs), 1)
        self.assertEqual(bundle.drcs[0]["drc_certificate_no"], "DRC/2024/00002/Indore")

    def test_project_details_shape_maps_to_p_fields(self):
        body = generating_body(TDR_DRC["data"][0]["project_details"][0], [], [])
        self.assertEqual(body["p_project_name"], "Mhow Naka to Tori Corner")
        self.assertEqual(body["p_implementation_agency"], "Indore Municipal Corporation")

    def test_repeat_owner_is_treated_as_already_stored(self):
        body = {
            "success": False,
            "message": "Duplicate Owner ID",
            "error": "Owner ID 101 is already registered under Application ID TDR202471184557197",
            "code": "DUPLICATE_OWNER",
        }
        self.assertTrue(is_duplicate(400, body))


class PhaseTests(unittest.TestCase):
    def test_phase1_missing_on_chain_is_mismatch(self):
        record = verify_certificate(FakeTdr(), FakeChain(), "DRC/2024/00002/Indore")
        self.assertEqual(record["status"], "MISMATCH")
        self.assertIn("missing on blockchain", record["message"])
        self.assertEqual(record["diffs"][0]["blockchain_api"], "GET /Agency/GetDRCDetails")
        kinds = [item["kind"] for item in record["records"]]
        self.assertEqual(kinds, ["DRC", "Owner", "Generating area"])

    def test_phase1_match(self):
        expected = drc_body(TDR_DRC["data"][0]["certificate_details"][0])
        record = verify_certificate(FakeTdr(), FakeChain(drc=expected), "DRC/2024/00002/Indore")
        self.assertEqual(record["status"], "MATCH")
        self.assertEqual(record["diffs"], [])
        self.assertEqual([item["status"] for item in record["records"]], ["MATCH", "MATCH", "MATCH"])
        self.assertEqual(record["flg"], "FIRST_OWNER")
        self.assertEqual(record["chain_action"], "generate")
        self.assertTrue(record["on_chain"])

    def test_phase1_api_failure_is_not_mismatch(self):
        class Down:
            def drc_by_certificate(self, certificate_no):
                raise ApiError(503, "unavailable", {"error": "unavailable"}, True)

        record = verify_certificate(Down(), FakeChain(), "DRC/2024/00002/Indore")
        self.assertEqual(record["status"], "API_FAILURE")

    def test_pipeline_writes_in_order_and_stops_on_drc_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            service = SyncService(
                settings(os.path.join(folder, "state.json")),
                FakeTdr(),
                FakeChain(mismatch=True),
                StateStore(os.path.join(folder, "state.json")),
            )
            job = service.run_application(
                "legacy",
                "TDR202471184557197",
                certificate_nos=["DRC/2024/00002/Indore"],
                scan_certs=False,
            )
        self.assertEqual(job["status"], "FAILED")
        self.assertEqual(job["stages"]["GENERATING_AREA"]["status"], "MATCH")
        self.assertEqual(job["stages"]["OWNER_DETAIL"]["status"], "MATCH")
        self.assertEqual(job["stages"]["DRC_UPLOAD"]["status"], "MISMATCH")
        diffs = job["stages"]["DRC_UPLOAD"]["diffs"]
        self.assertTrue(diffs)
        self.assertEqual(diffs[0]["field"], "remaining_value_tdr")
        self.assertEqual(diffs[0]["tdr_received"], "75.92")
        self.assertEqual(diffs[0]["blockchain_received"], "1")
        self.assertEqual(diffs[0]["tdr_api"], "GET /GetDetailByCertificateNo")
        self.assertEqual(diffs[0]["blockchain_api"], "GET /Agency/GetDRCDetails")
        self.assertNotIn("TRANSFER", job["stages"])
        paths = [path for path, _body in service.chain.writes]
        self.assertEqual(
            paths,
            [
                "/Agency/InsertGeneratingArea",
                "/Agency/InsertOwnerDetail",
                "/Department/DRCUpload",
            ],
        )

    def test_pipeline_match_skips_empty_transfer(self):
        with tempfile.TemporaryDirectory() as folder:
            chain = FakeChain()
            service = SyncService(
                settings(os.path.join(folder, "state.json")),
                FakeTdr(),
                chain,
                StateStore(os.path.join(folder, "state.json")),
            )
            job = service.run_application(
                "live",
                "TDR202471184557197",
                certificate_nos=["DRC/2024/00002/Indore"],
                scan_certs=False,
            )
        self.assertEqual(job["status"], "SUCCESS")
        self.assertEqual(job["stages"]["TRANSFER"]["status"], "SKIPPED")
        self.assertEqual(job["last_successful_stage"], "TRANSFER")

    def test_phase2_lists_extracted_ids_and_stops(self):
        from schedulermp.runs import RunControl

        class Two(FakeTdr):
            def application_list(self):
                return [{"application_id": "ONE"}, {"application_id": "TWO"}]

        class StopOnLoad(RunControl):
            def detail(self, application_id, stage, message, log=False):
                super().detail(application_id, stage, message, log=log)
                if stage == "LOAD":
                    self.request_stop()

        with tempfile.TemporaryDirectory() as folder:
            control = StopOnLoad(2)
            service = SyncService(
                settings(os.path.join(folder, "state.json")),
                Two(),
                FakeChain(),
                StateStore(os.path.join(folder, "state.json")),
            )
            jobs = service.run_legacy_batch(control=control)
            control.complete("Stopped")
        self.assertEqual(control.snapshot()["extracted"], ["ONE", "TWO"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["application_id"], "ONE")
        self.assertEqual(jobs[0]["status"], "STOPPED")
        items = {item["applicationId"]: item["status"] for item in control.snapshot()["items"]}
        self.assertEqual(items["ONE"], "STOPPED")
        self.assertEqual(items["TWO"], "NOT_STARTED")
        self.assertIn("Extracted 2 application id(s)", " ".join(control.snapshot()["log"]))

    def test_phase1_csv_marks_on_chain_rows(self):
        text = verifications_csv(
            {
                "DRC/1": {
                    "certificate_no": "DRC/1",
                    "application_id": "APP",
                    "status": "MATCH",
                    "on_chain": True,
                    "flg": "UTILIZATION_OWNER",
                    "chain_action": "update",
                    "message": "DRC fields match",
                    "checked_at": "2026-11-10T00:00:00+00:00",
                    "diffs": [],
                }
            }
        )
        self.assertIn("certificate_no,application_id,status,on_chain,flg,chain_action", text)
        self.assertIn("UTILIZATION_OWNER", text)
        self.assertIn(",yes,", text)


if __name__ == "__main__":
    unittest.main()
