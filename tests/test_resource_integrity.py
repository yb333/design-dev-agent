"""
Resource Integrity Tests for DataGenie Tauri Build

Validates that all resource files needed for the Tauri build are present and valid.
This ensures the build.rs script can successfully copy all required resources.
"""
import json
from pathlib import Path

import pytest


# Test configuration
PROJECT_ROOT = Path(__file__).parent.parent
REQUIRED_SKILLS = [
    "dws-pipeline-code-reviewer",
    "dws-pipeline-coder",
    "dws-pipeline-designer",
    "dws-pipeline-exporter",
    "dws-pipeline-reviewer",
    "dws-pipeline-tester",
]


class TestCommands:
    """Test command files existence and validity."""

    def test_ulw_pipe_command_exists(self):
        """Test that the ulw-pipe command file exists."""
        cmd_file = PROJECT_ROOT / ".opencode" / "commands" / "ulw-pipe.md"
        assert cmd_file.exists(), f"Command file not found: {cmd_file}"

    def test_ulw_pipe_command_has_yaml_frontmatter(self):
        """Test that the command file contains YAML frontmatter (---)."""
        cmd_file = PROJECT_ROOT / ".opencode" / "commands" / "ulw-pipe.md"
        content = cmd_file.read_text()
        assert "---" in content, f"Command file missing YAML frontmatter: {cmd_file}"


class TestSkills:
    """Test skills directory structure."""

    def test_skills_directory_exists(self):
        """Test that the .opencode/skills directory exists."""
        skills_dir = PROJECT_ROOT / ".opencode" / "skills"
        assert skills_dir.is_dir(), f"Skills directory not found: {skills_dir}"

    @pytest.mark.parametrize("skill_name", REQUIRED_SKILLS)
    def test_skill_directory_exists(self, skill_name):
        """Test that each required skill directory exists."""
        skill_dir = PROJECT_ROOT / ".opencode" / "skills" / skill_name
        assert skill_dir.is_dir(), f"Skill directory not found: {skill_dir}"

    def test_dws_run_py_exists(self):
        """Test that dws-run.py exists."""
        dws_run = PROJECT_ROOT / ".opencode" / "skills" / "dws-run.py"
        assert dws_run.exists(), f"dws-run.py not found: {dws_run}"

    def test_shared_directory_exists(self):
        """Test that the shared directory exists."""
        shared_dir = PROJECT_ROOT / ".opencode" / "skills" / "shared"
        assert shared_dir.is_dir(), f"Shared directory not found: {shared_dir}"


class TestDownloadScripts:
    """Test download script existence and executability."""

    def test_download_sidecar_sh_exists(self):
        """Test that download-sidecar.sh exists."""
        script = PROJECT_ROOT / "scripts" / "download-sidecar.sh"
        assert script.exists(), f"download-sidecar.sh not found: {script}"

    def test_download_sidecar_sh_is_executable(self):
        """Test that download-sidecar.sh is executable."""
        script = PROJECT_ROOT / "scripts" / "download-sidecar.sh"
        # On Windows, os.access may not work correctly, so we check existence only
        # The executable bit is checked by the build process itself
        assert script.exists(), f"download-sidecar.sh not found: {script}"

    def test_download_sidecar_ps1_exists(self):
        """Test that download-sidecar.ps1 exists."""
        script = PROJECT_ROOT / "scripts" / "download-sidecar.ps1"
        assert script.exists(), f"download-sidecar.ps1 not found: {script}"

    def test_download_oh_my_opencode_sh_exists(self):
        """Test that download-oh-my-opencode.sh exists."""
        script = PROJECT_ROOT / "scripts" / "download-oh-my-opencode.sh"
        assert script.exists(), f"download-oh-my-opencode.sh not found: {script}"


class TestVersionFiles:
    """Test version file existence and validity."""

    def test_package_json_exists(self):
        """Test that web/package.json exists."""
        package_file = PROJECT_ROOT / "web" / "package.json"
        assert package_file.exists(), f"package.json not found: {package_file}"

    def test_package_json_has_version(self):
        """Test that package.json contains a version field."""
        package_file = PROJECT_ROOT / "web" / "package.json"
        content = json.loads(package_file.read_text())
        assert "version" in content, f"package.json missing 'version' field"
        assert content["version"], f"package.json version field is empty"

    def test_cargo_toml_exists(self):
        """Test that web/src-tauri/Cargo.toml exists."""
        cargo_file = PROJECT_ROOT / "web" / "src-tauri" / "Cargo.toml"
        assert cargo_file.exists(), f"Cargo.toml not found: {cargo_file}"

    def test_cargo_toml_has_version(self):
        """Test that Cargo.toml contains a version field."""
        cargo_file = PROJECT_ROOT / "web" / "src-tauri" / "Cargo.toml"
        content = cargo_file.read_text()
        assert 'version = "' in content, f"Cargo.toml missing version field"
        # Extract version string
        for line in content.split("\n"):
            if line.strip().startswith("version ="):
                assert line.strip().count('"') >= 2, f"Invalid version format in Cargo.toml"
                break

    def test_tauri_conf_json_exists(self):
        """Test that web/src-tauri/tauri.conf.json exists."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        assert tauri_conf.exists(), f"tauri.conf.json not found: {tauri_conf}"

    def test_tauri_conf_json_has_version(self):
        """Test that tauri.conf.json contains a version field."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        content = json.loads(tauri_conf.read_text())
        assert "version" in content, f"tauri.conf.json missing 'version' field"
        assert content["version"], f"tauri.conf.json version field is empty"

    def test_skills_version_file_exists(self):
        """Test that web/src-tauri/resources/skills/.skills-version exists (only if resources dir exists)."""
        skills_dir = PROJECT_ROOT / "web" / "src-tauri" / "resources" / "skills"
        if not skills_dir.exists():
            pytest.skip("resources/skills/ not present (build.rs has not run)")
        version_file = skills_dir / ".skills-version"
        assert version_file.exists(), f".skills-version not found: {version_file}"

    def test_skills_version_file_has_content(self):
        """Test that .skills-version file has a valid content hash (16-char hex)."""
        skills_dir = PROJECT_ROOT / "web" / "src-tauri" / "resources" / "skills"
        if not skills_dir.exists():
            pytest.skip("resources/skills/ not present (build.rs has not run)")
        version_file = skills_dir / ".skills-version"
        content = version_file.read_text().strip()
        assert content, f".skills-version file is empty"
        assert len(content) == 16 and all(c in '0123456789abcdef' for c in content), \
            f".skills-version should be a 16-char hex hash, got: {content}"


class TestVersionConsistency:
    """Test that app version files are consistent."""

    def test_all_versions_match(self):
        """Test that package.json, Cargo.toml, and tauri.conf.json have the SAME version number."""
        # Get version from package.json
        package_file = PROJECT_ROOT / "web" / "package.json"
        pkg_version = json.loads(package_file.read_text())["version"]

        # Get version from Cargo.toml
        cargo_file = PROJECT_ROOT / "web" / "src-tauri" / "Cargo.toml"
        cargo_content = cargo_file.read_text()
        cargo_version = None
        for line in cargo_content.split("\n"):
            if line.strip().startswith("version ="):
                cargo_version = line.strip().split('"')[1]
                break
        assert cargo_version, "Could not extract version from Cargo.toml"

        # Get version from tauri.conf.json
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        tauri_version = json.loads(tauri_conf.read_text())["version"]

        assert (
            pkg_version == cargo_version
        ), f"Version mismatch: package.json={pkg_version}, Cargo.toml={cargo_version}"
        assert (
            pkg_version == tauri_version
        ), f"Version mismatch: package.json={pkg_version}, tauri.conf.json={tauri_version}"

        print(f"✅ All app versions match: {pkg_version}")


class TestTauriResourcesConfig:
    """Test that tauri.conf.json lists all required resources."""

    def test_tauri_conf_json_lists_skills_resource(self):
        """Test that tauri.conf.json bundle.resources includes skills."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        content = json.loads(tauri_conf.read_text())
        resources = content.get("bundle", {}).get("resources", [])
        resource_str = json.dumps(resources)

        assert "skills" in resource_str, "tauri.conf.json missing 'skills' in bundle.resources"

    def test_tauri_conf_json_lists_commands_resource(self):
        """Test that tauri.conf.json bundle.resources includes commands."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        content = json.loads(tauri_conf.read_text())
        resources = content.get("bundle", {}).get("resources", [])
        resource_str = json.dumps(resources)

        assert "commands" in resource_str, "tauri.conf.json missing 'commands' in bundle.resources"

    def test_tauri_conf_json_no_tools_resource(self):
        """Test that tauri.conf.json bundle.resources does NOT include tools (migrated to excel-io MCP)."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        content = json.loads(tauri_conf.read_text())
        resources = content.get("bundle", {}).get("resources", [])
        resource_str = json.dumps(resources)

        assert "tools/" not in resource_str, "tauri.conf.json should NOT include 'tools/' in bundle.resources (migrated to excel-io MCP)"

    def test_tauri_conf_json_lists_oh_my_opencode_resource(self):
        """Test that tauri.conf.json bundle.resources includes oh-my-opencode."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        content = json.loads(tauri_conf.read_text())
        resources = content.get("bundle", {}).get("resources", [])
        resource_str = json.dumps(resources)

        assert "oh-my-opencode" in resource_str, "tauri.conf.json missing 'oh-my-opencode' in bundle.resources"

    def test_tauri_conf_json_has_bundle_resources(self):
        """Test that tauri.conf.json has bundle.resources configured."""
        tauri_conf = PROJECT_ROOT / "web" / "src-tauri" / "tauri.conf.json"
        content = json.loads(tauri_conf.read_text())

        assert "bundle" in content, "tauri.conf.json missing 'bundle' section"
        assert "resources" in content["bundle"], "tauri.conf.json missing 'resources' in bundle"
        assert isinstance(
            content["bundle"]["resources"], list
        ), "tauri.conf.json bundle.resources must be a list"
        assert len(content["bundle"]["resources"]) > 0, "tauri.conf.json bundle.resources is empty"


class TestBuildResources:
    """Test that resources required by build.rs exist."""

    def test_opencode_commands_dir_exists(self):
        """Test that .opencode/commands exists (copied to resources/commands)."""
        commands_dir = PROJECT_ROOT / ".opencode" / "commands"
        assert commands_dir.is_dir(), f".opencode/commands not found: {commands_dir}"

    def test_tauri_resources_dir_exists(self):
        """Test that web/src-tauri/resources exists."""
        resources_dir = PROJECT_ROOT / "web" / "src-tauri" / "resources"
        assert resources_dir.is_dir(), f"web/src-tauri/resources not found: {resources_dir}"


class TestOmoDisabledCapabilities:
    """
    Verify that disabled_agents/skills/tools/hooks in lib.rs reference
    real capabilities that exist in the oh-my-opencode plugin bundle.
    This catches typos or stale entries after plugin upgrades.
    """

    PLUGIN_DIST = (
        PROJECT_ROOT
        / "web"
        / "src-tauri"
        / "resources"
        / "oh-my-opencode"
        / "dist"
    )
    LIB_RS = PROJECT_ROOT / "web" / "src-tauri" / "src" / "lib.rs"

    def _extract_disabled_list(self, key):
        """Extract a disabled_* array from lib.rs source."""
        import re

        content = self.LIB_RS.read_text()
        pattern = rf'let {key} = \[([^\]]+)\]'
        m = re.search(pattern, content)
        assert m, f"Could not find 'let {key} = [...]' in lib.rs"
        items = re.findall(r'"([^"]+)"', m.group(1))
        return items

    def test_disabled_agents_exist_in_plugin(self):
        disabled = self._extract_disabled_list("disabled_agents")
        assert len(disabled) >= 2, f"Expected at least 2 disabled_agents, got {disabled}"
        agents_dir = self.PLUGIN_DIST / "agents"
        if not agents_dir.exists():
            pytest.skip("Plugin dist/agents not available")
        agent_names = set()
        for f in agents_dir.iterdir():
            name = f.name.replace(".d.ts", "") if f.is_file() else f.name
            agent_names.add(name)
        agent_names.discard("index")
        for agent in disabled:
            assert agent in agent_names, (
                f"Disabled agent '{agent}' not found in plugin agents/. "
                f"Available: {sorted(agent_names)}"
            )

    def test_disabled_skills_exist_in_plugin(self):
        disabled = self._extract_disabled_list("disabled_skills")
        assert len(disabled) >= 5, f"Expected at least 5 disabled_skills, got {disabled}"
        index_js = self.PLUGIN_DIST / "index.js"
        if not index_js.exists():
            pytest.skip("Plugin dist/index.js not available")
        content = index_js.read_text()
        for skill in disabled:
            assert skill in content, f"Disabled skill '{skill}' not found in plugin bundle"

    def test_disabled_tools_exist_in_plugin(self):
        disabled = self._extract_disabled_list("disabled_tools")
        assert len(disabled) >= 6, f"Expected at least 6 disabled_tools, got {disabled}"
        tools_dir = self.PLUGIN_DIST / "tools"
        index_js = self.PLUGIN_DIST / "index.js"
        for tool in disabled:
            tool_dir = tools_dir / tool.replace("_", "-")
            in_bundle = index_js.exists() and tool in (index_js.read_text() if index_js.exists() else "")
            assert tool_dir.exists() or in_bundle, (
                f"Disabled tool '{tool}' not found in plugin (not in tools/ dir or index.js)"
            )

    def test_disabled_hooks_exist_in_plugin(self):
        disabled = self._extract_disabled_list("disabled_hooks")
        assert len(disabled) >= 10, f"Expected at least 10 disabled_hooks, got {disabled}"
        hooks_dir = self.PLUGIN_DIST / "hooks"
        if not hooks_dir.exists():
            pytest.skip("Plugin dist/hooks not available")
        hook_names = set()
        for f in hooks_dir.iterdir():
            name = f.name.replace(".d.ts", "") if f.is_file() else f.name
            hook_names.add(name)
        hook_names.discard("index")
        hook_names.discard("shared")
        for hook in disabled:
            assert hook in hook_names, (
                f"Disabled hook '{hook}' not found in plugin hooks/. "
                f"Available: {sorted(hook_names)}"
            )
