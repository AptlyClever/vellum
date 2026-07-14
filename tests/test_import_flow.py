"""Import pack checklist + stage upload."""

from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend import import_flow as import_flow_mod
from backend import register as register_mod


def test_content_root_from_folder_name() -> None:
    assert import_flow_mod.content_root_from_folder_name("FireworksV1") == "/Game/FireworksV1"


def test_import_status_and_mark(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "reg.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_SEED_PATH", str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    register_mod.ensure_register(force_reseed=True)
    monkeypatch.setattr(
        import_flow_mod.ue_hosts_mod,
        "path_known_in_content_scan",
        lambda path, host_id=None: {"name": "FireworksV1", "path": path},
    )
    client = TestClient(app)
    asset_id = "fireworks-vol-1-niagara"
    st = client.get(f"/api/assets/{asset_id}/import")
    assert st.status_code == 200
    body = st.json()
    assert body["asset_id"] == asset_id
    assert body["next_step"] in {"redeemed", "in_project", "staged", "captured", None}

    marked = client.post(
        f"/api/assets/{asset_id}/import/mark",
        json={"step": "redeemed"},
    )
    assert marked.status_code == 200
    assert marked.json()["asset"]["redemption_status"] == "redeemed"

    need_path = client.post(
        f"/api/assets/{asset_id}/import/mark",
        json={"step": "in_project"},
    )
    assert need_path.status_code == 400

    in_proj = client.post(
        f"/api/assets/{asset_id}/import/mark",
        json={
            "step": "in_project",
            "host_content_path": r"F:\Games\AuroraVellum\Content\FireworksV1",
        },
    )
    assert in_proj.status_code == 200
    assert in_proj.json()["import"]["host_content_path"]


def test_stage_upload_extracts(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "reg.yaml"
    vault = tmp_path / "vault"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_SEED_PATH", str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(vault))
    register_mod.ensure_register(force_reseed=True)
    client = TestClient(app)
    asset_id = "hangar-x"
    pack = tmp_path / "pack_src"
    pack.mkdir()
    (pack / "readme.txt").write_text("hi", encoding="utf-8")
    zpath = tmp_path / "pack.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(pack / "readme.txt", "readme.txt")

    with zpath.open("rb") as fh:
        res = client.post(
            f"/api/assets/{asset_id}/import/stage-upload",
            data={
                "host_content_path": r"F:\Games\AuroraVellum\Content\HangarX",
                "content_folder_name": "HangarX",
            },
            files={"archive": ("pack.zip", fh, "application/zip")},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["content_root"] == "/Game/HangarX"
    assert body["file_count"] >= 1
    assert Path(body["raw_location"]).exists()
    st = client.get(f"/api/assets/{asset_id}/import").json()
    assert any(s["id"] == "staged" and s["done"] for s in st["steps"])


def test_import_queue(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "reg.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_SEED_PATH", str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    register_mod.ensure_register(force_reseed=True)

    from backend import ue_hosts as ue_hosts_mod

    monkeypatch.setattr(
        ue_hosts_mod,
        "list_content_folders",
        lambda host_id=None: {"schema_version": 1, "folders": [], "count": 0},
    )
    monkeypatch.setattr(import_flow_mod, "fab_install_candidates", lambda asset_id: [])
    monkeypatch.setenv("VELLUM_DERIVED_OUTPUTS_PATH", str(tmp_path / "empty-outputs.yaml"))
    (tmp_path / "empty-outputs.yaml").write_text("schema_version: 1\noutputs: []\n", encoding="utf-8")
    monkeypatch.setenv("VELLUM_FAB_LISTINGS_DB", str(tmp_path / "no-listings.db"))
    from backend import fab_library as fab_library_mod

    fab_library_mod.clear_cache()
    import_flow_mod.clear_ops_caches()

    client = TestClient(app)
    q = client.get("/api/import/queue?engine=unreal&limit=100")
    assert q.status_code == 200
    body = q.json()
    assert "items" in body
    assert "blocked_epic_count" in body
    assert "deferred_epic_count" in body
    # Empty host Content + empty vault + no Fab map → Epic wall only.
    assert body["count"] == 0
    assert body["blocked_epic_count"] > 0
    assert body["deferred_epic_count"] == 3
    # No launcher catalog available → generic UE packs are "unseen", while
    # known Fab Complete Project listings still carry the migration workflow.
    # next_step carries the acquisition method, never a bogus "download" instruction.
    methods = {item["asset_id"]: item["next_step"] for item in body["deferred_epic"]}
    assert methods["the-count-s-church"] == fab_library_mod.METHOD_FAB_CREATE_PROJECT_MIGRATE
    assert methods["abandoned-cabin"] == fab_library_mod.METHOD_FAB_CREATE_PROJECT_MIGRATE
    assert methods["loot-drops-vol-2-niagara"] == fab_library_mod.METHOD_FAB_CREATE_PROJECT_MIGRATE
    for item in body["deferred_epic"]:
        assert item["blocked"] is False
        assert "Create Project" in item["acquisition"]["operator_hint"]
        assert "Migrate" in item["acquisition"]["operator_hint"]
    for item in body["blocked_epic"]:
        assert item["next_step"] == fab_library_mod.METHOD_FAB_ADD_UNSEEN
        assert "Add to Project" in item["acquisition"]["operator_hint"]

    # Superseded register rows (replaced by a renamed/merged row) must not
    # resurface as blocked work in the queue.
    superseded_id = body["blocked_epic"][0]["asset_id"]
    register_mod.patch_asset(superseded_id, redemption_status="superseded")
    import_flow_mod.clear_ops_caches()
    body2 = client.get("/api/import/queue?engine=unreal&limit=100").json()
    assert superseded_id not in {i["asset_id"] for i in body2["blocked_epic"]}
    assert superseded_id not in {i["asset_id"] for i in body2["items"]}


def test_skip_folders_excludes_python_tooling() -> None:
    assert "Python" in import_flow_mod.SKIP_FOLDERS
    assert "Vellum" in import_flow_mod.SKIP_FOLDERS


def test_content_folders_and_host_stage_enqueue(tmp_path: Path, monkeypatch) -> None:
    import json

    from backend import ue_hosts as ue_hosts_mod

    reg = tmp_path / "reg.yaml"
    specs = tmp_path / "specs"
    specs.mkdir()
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_SEED_PATH", str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_UE_HOST_SPECS_DIR", str(specs))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite"))
    register_mod.ensure_register(force_reseed=True)
    hangar_path = r"F:\Games\AuroraVellum\Content\HangarX"
    (specs / "aurora.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "host_id": "aurora",
                "updated_at": "2026-07-14T00:00:00+00:00",
                "specs": {
                    "content_folders": [
                        {
                            "name": "HangarX",
                            "path": hangar_path,
                            "project_root": r"F:\Games\AuroraVellum",
                            "engine": "unreal",
                        }
                    ],
                    "content_root_path": r"F:\Games\AuroraVellum\Content",
                    "fab_target_project": r"F:\Games\AuroraVellum\AuroraVellum.uproject",
                    "fab_target_label": "AuroraVellum (F:)",
                },
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    folders = client.get("/api/ue/hosts/content-folders?host_id=aurora")
    assert folders.status_code == 200
    assert folders.json()["count"] == 1
    assert folders.json()["folders"][0]["name"] == "HangarX"
    assert "fab_target_project" in folders.json()

    refresh = client.post("/api/ue/hosts/content-folders/refresh?host_id=aurora")
    assert refresh.status_code == 200
    assert refresh.json()["job"]["kind"] == "host_scan"

    bad = client.post(
        "/api/assets/hangar-x/import/stage",
        json={
            "host_content_path": r"C:\dev\AuroraVellum\Content\HangarX",
            "content_folder_name": "HangarX",
            "ue_host": "aurora",
        },
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "host_path_not_in_scan"

    stage = client.post(
        "/api/assets/hangar-x/import/stage",
        json={
            "host_content_path": hangar_path,
            "content_folder_name": "HangarX",
            "ue_host": "aurora",
        },
    )
    assert stage.status_code == 200
    assert stage.json()["job"]["kind"] == "host_stage"

    listed = ue_hosts_mod.list_content_folders("aurora")
    assert listed["count"] == 1
    assert ue_hosts_mod.path_known_in_content_scan(hangar_path)


def test_fab_install_enqueue(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "reg.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_SEED_PATH", str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite"))
    register_mod.ensure_register(force_reseed=True)

    from backend import ue_hosts as ue_hosts_mod

    # Isolate from live Aurora Content scan (hangar already on F: would skip VaultCache).
    monkeypatch.setattr(
        ue_hosts_mod,
        "list_content_folders",
        lambda host_id=None: {"schema_version": 1, "folders": [], "count": 0},
    )

    client = TestClient(app)

    assert import_flow_mod.fab_install_candidates("hangar-x")
    bad = client.post(
        "/api/assets/mega-marble-material-4k/import/fab-install",
        json={"auto_stage": False},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "no_fab_install_map"

    ok = client.post(
        "/api/assets/hangar-x/import/fab-install",
        json={"ue_host": "aurora", "auto_stage": True},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["job"]["kind"] == "host_fab_install"
    assert "Hangar-X" in body["candidates"]

    batch = client.post(
        "/api/import/fab-install-batch",
        json={"limit": 3, "auto_stage": True},
    )
    assert batch.status_code == 200
    assert batch.json()["enqueued"] >= 1


def test_register_orphans(tmp_path: Path, monkeypatch) -> None:
    import json

    reg = tmp_path / "reg.yaml"
    specs = tmp_path / "specs"
    specs.mkdir()
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv("VELLUM_SEED_PATH", str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"))
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_UE_HOST_SPECS_DIR", str(specs))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite"))
    register_mod.ensure_register(force_reseed=True)
    free_path = r"F:\Games\AuroraVellum\Content\CookiePack"
    (specs / "aurora.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "host_id": "aurora",
                "updated_at": "2026-07-14T00:00:00+00:00",
                "specs": {
                    "content_folders": [
                        {
                            "name": "CookiePack",
                            "path": free_path,
                            "project_root": r"F:\Games\AuroraVellum",
                            "engine": "unreal",
                        }
                    ],
                    "content_root_path": r"F:\Games\AuroraVellum\Content",
                },
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    cov = client.get("/api/import/coverage?engine=unreal").json()
    assert any(o["folder"] == "CookiePack" for o in cov["orphans"])

    res = client.post(
        "/api/import/register-orphans",
        json={"folders": ["CookiePack"], "auto_stage": True, "ue_host": "aurora"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["registered"] == 1
    asset = body["results"][0]["asset"]
    assert asset["content_folder_name"] == "CookiePack"
    assert asset["host_content_path"] == free_path
    assert body["results"][0]["job"]["kind"] == "host_stage"

    cov2 = client.get("/api/import/coverage?engine=unreal").json()
    assert not any(o["folder"] == "CookiePack" for o in cov2["orphans"])
    assert any(d["folder"] == "CookiePack" for d in cov2["on_disk"])



def test_resolve_folder_fuzzy_maps_marble(tmp_path: Path, monkeypatch) -> None:
    from backend import import_flow as import_flow_mod
    from backend import register as register_mod

    reg = tmp_path / "reg.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv(
        "VELLUM_SEED_PATH",
        str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"),
    )
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    register_mod.ensure_register(force_reseed=True)

    assert (
        import_flow_mod.resolve_folder_to_asset_id("MegaMarbleMaterial")
        == "mega-marble-material-4k"
    )
    # Exact map still wins for known folders
    assert import_flow_mod.resolve_folder_to_asset_id("FireworksV1") == "fireworks-vol-1-niagara"


def test_game_ready_elements_count_as_conversion_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(tmp_path / "reg.yaml"))
    monkeypatch.setenv(
        "VELLUM_SEED_PATH",
        str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"),
    )
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_DERIVED_OUTPUTS_PATH", str(tmp_path / "outputs.yaml"))
    (tmp_path / "outputs.yaml").write_text("schema_version: 1\noutputs: []\n", encoding="utf-8")
    monkeypatch.setenv("VELLUM_GAME_READY_PATH", str(tmp_path / "game-ready.yaml"))
    register_mod.ensure_register(force_reseed=True)
    import_flow_mod.clear_ops_caches()

    assert "fireworks-vol-1-niagara" not in import_flow_mod._lookdev_asset_ids()

    from backend import game_ready as game_ready_mod

    src = tmp_path / "SM_Rocket.glb"
    src.write_bytes(b"glb")
    game_ready_mod.register_element(
        asset_id="fireworks-vol-1-niagara",
        kind="model-gltf",
        path=src,
        pack="FireworksV1",
    )
    import_flow_mod.clear_ops_caches()
    assert "fireworks-vol-1-niagara" in import_flow_mod._lookdev_asset_ids()


def test_availability_row_priority() -> None:
    assert import_flow_mod.availability_row(
        on_disk=True, staged=True, lookdev=True, installable=False
    )["state"] == "ready"
    assert import_flow_mod.availability_row(
        on_disk=True, staged=False, lookdev=False, installable=False
    )["state"] == "on_disk"
    assert import_flow_mod.availability_row(
        on_disk=False, staged=False, lookdev=False, installable=True
    )["state"] == "installable"
    assert import_flow_mod.availability_row(
        on_disk=False, staged=False, lookdev=False, installable=False, deferred=True
    )["state"] == "deferred"
    assert import_flow_mod.availability_row(
        on_disk=False, staged=True, lookdev=True, installable=False
    )["state"] == "vault"
    assert import_flow_mod.availability_row(
        on_disk=False, staged=False, lookdev=False, installable=False
    )["state"] == "need_download"


def test_assets_list_includes_availability(tmp_path: Path, monkeypatch) -> None:
    reg = tmp_path / "reg.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv(
        "VELLUM_SEED_PATH",
        str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"),
    )
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_DERIVED_PATH", str(tmp_path / "derived.yaml"))
    register_mod.ensure_register(force_reseed=True)
    monkeypatch.setattr(
        import_flow_mod.ue_hosts_mod,
        "list_content_folders",
        lambda host_id=None: {"folders": []},
    )
    client = TestClient(app)
    res = client.get("/api/assets?engine=unreal")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] > 0
    assert "availability" in body["assets"][0]
    assert body["assets"][0]["availability"]["state"] in import_flow_mod.AVAILABILITY_STATES

    filt = client.get("/api/assets?engine=unreal&available=need_download")
    assert filt.status_code == 200
    assert all(
        a["availability"]["state"] == "need_download" for a in filt.json()["assets"]
    )


def test_lookdev_mode_splits_niagara_vs_texture() -> None:
    assert (
        import_flow_mod.lookdev_mode_for_asset(
            {"id": "hangar-x", "display_name": "HANGAR-X", "package_type": "Unreal Engine environment"}
        )
        == "texture"
    )
    assert (
        import_flow_mod.lookdev_mode_for_asset(
            {
                "id": "toon-abilities-vol-1-niagara",
                "display_name": "Toon Abilities Vol.1 - Niagara",
                "package_type": "Unreal Engine Niagara VFX",
            }
        )
        == "niagara_mrq"
    )


def test_parse_progress_log_and_ops_finish_shape(tmp_path: Path, monkeypatch) -> None:
    parsed = import_flow_mod.parse_progress_log(
        "2026-07-14T00:00:00+00:00 | Inventory: 11 systems\n---\n"
        "2026-07-14T00:01:00+00:00 | Authoring 11 systems on Lookdev Studio…\n---\n"
    )
    assert parsed["systems_total"] == 11
    assert "Authoring" in parsed["phase"]

    reg = tmp_path / "reg.yaml"
    monkeypatch.setenv("VELLUM_REGISTER_PATH", str(reg))
    monkeypatch.setenv(
        "VELLUM_SEED_PATH",
        str(Path(__file__).resolve().parents[1] / "config" / "humble-seed.yaml"),
    )
    monkeypatch.setenv("VELLUM_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("VELLUM_JOBS_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    register_mod.ensure_register(force_reseed=True)
    client = TestClient(app)
    ops = client.get("/api/ops/now?engine=unreal").json()
    assert "finish" in ops
    assert "percent_complete" in ops["finish"]
    assert ops["operator"]["redeem"] == "closed"
    assert ops["operator"]["responsibility"] == "none"

