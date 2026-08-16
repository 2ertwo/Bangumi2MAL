import csv

from bangumi2mal.models import SyncItemResult, SyncRunResult
from bangumi2mal.reporting import export_run


def test_export_creates_success_unresolved_and_complete_csv(tmp_path):
    run = SyncRunResult("run-csv", True, "start", "finish", "completed")
    run.items = [
        SyncItemResult(1, "成功", 2, "Success", "automatic", 0.99, "planned", {"score": 9}),
        SyncItemResult(3, "待处理", None, "", "ambiguous", 0.8, "unresolved", error="ambiguous"),
    ]
    output = export_run(run, tmp_path)
    assert {path.name for path in output.iterdir()} == {"all.csv", "synced.csv", "unresolved.csv"}
    with (output / "unresolved.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["bangumi_title"] == "待处理"
    assert rows[0]["result"] == "unresolved"
