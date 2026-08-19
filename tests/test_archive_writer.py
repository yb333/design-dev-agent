"""archive_writer 测试：档案写回与序号顺延（docs/specs/opt/02 §〇）。"""
import json

from archive_writer import write_archive, next_seq, main


def _mk(p, files: dict):
    p.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        f = p / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")


TS = {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_d", "cn": ""}}}}


class TestArchive:
    def test_first_write_creates_001(self, tmp_path):
        ts_dir = tmp_path / "src"; _mk(ts_dir, {"ts_v2.json": json.dumps(TS, ensure_ascii=False),
                                                "etl/R0001.sql": "SELECT 1",
                                                "ddl_full/create_table_dwb_x_d.sql": "CREATE..."})
        dest = write_archive(tmp_path / "archives", "dws", "dwb_x_d",
                             ts_dir / "ts_v2.json", ts_dir / "etl", ts_dir / "ddl_full",
                             ts_dir / "decisions.yaml")
        assert dest.name.startswith("001_")
        assert (dest / "ts_v2.json").exists()
        assert (dest / "etl/R0001.sql").exists()
        assert (dest / "ddl/create_table_dwb_x_d.sql").exists(), "全量 DDL 统一落 dest/ddl"

    def test_seq_increments(self, tmp_path):
        asset = tmp_path / "archives" / "dws" / "dwb_x_d" / "001_20260101"
        asset.mkdir(parents=True)
        assert next_seq(asset.parent) == 2
        assert next_seq(tmp_path / "archives" / "dws" / "nope") == 1

    def test_main(self, tmp_path):
        ts_dir = tmp_path / "src"; _mk(ts_dir, {"ts.json": json.dumps(TS, ensure_ascii=False),
                                                "etl/R0001.sql": "SELECT 1",
                                                "ddl/x.sql": "CREATE..."})
        rc = main(["--ts", str(ts_dir / "ts.json"), "--etl-dir", str(ts_dir / "etl"),
                   "--ddl-dir", str(ts_dir / "ddl"),
                   "--archives-root", str(tmp_path / "archives")])
        assert rc == 0
        dirs = list((tmp_path / "archives" / "dws" / "dwb_x_d").iterdir())
        assert len(dirs) == 1 and dirs[0].name.startswith("001_")
