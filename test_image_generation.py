"""Unit tests for /image command, workflow patching, and safety filters.

All ComfyUI interactions are mocked — no real GPU required.
"""

import copy
import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace

import src.config as config_module
from src.commands import image as image_cmd
from src.services.image_generation_service import (
    _find_positive_node,
    _find_negative_node,
    _find_lora_nodes,
    _find_seed_node,
    _find_dimensions_node,
    _find_save_prefix_node,
    load_workflow,
    patch_workflow,
)
from src.services.comfyui_client import _sanitize_prompt_for_comfyui
from src.services.image_prompt_service import (
    _check_blocked,
    ImagePromptSpec,
)


# ── helpers ─────────────────────────────────────────────────────────────

_ANIMA_ENHANCED = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3}},
    "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "q.safetensors", "type": "stable_diffusion", "device": "default"}},
    "11": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["2", 0], "lora_name": "natsume_anan_v3.safetensors", "strength_model": 0.8}},
    "12": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["11", 0], "lora_name": "natsume_anan_v3.safetensors", "strength_model": 0.0}},
    "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": "masterpiece, best quality, score_7, safe, 1girl, natsume_anan"}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": "worst quality, low quality, bad hands"}},
    "6": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
    "7": {"class_type": "KSampler", "inputs": {"model": ["12", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "seed": 260703201, "steps": 32, "cfg": 4.5, "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1}},
    "8": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "15": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["8", 0]}},
    "16": {"class_type": "SaveImage", "inputs": {"images": ["15", 0], "filename_prefix": "anima_enhanced_final"}},
    "client_id": "test-client",
}


def _make_fake_config(**overrides):
    defaults = {
        "image_enable": True, "image_admin_only": False, "image_chat_tool_enable": False,
        "comfyui_base_url": "http://127.0.0.1:8188", "comfyui_timeout_seconds": 30,
        "comfyui_client_id": "test-client", "image_project_dir": "",
        "comfyui_workflow_api_path": "", "image_default_preset": "highres_output",
        "comfyui_positive_node_id": "", "comfyui_negative_node_id": "",
        "comfyui_preset_node_id": "", "comfyui_seed_node_id": "",
        "comfyui_width_node_id": "", "comfyui_height_node_id": "",
        "comfyui_steps_node_id": "", "comfyui_cfg_node_id": "",
        "comfyui_character_lora_node_id": "", "comfyui_style_lora_node_id": "",
        "comfyui_save_prefix_node_id": "",
        "image_use_character_lora": False, "image_character_lora_name": "",
        "image_character_lora_strength": 0.0,
        "image_use_style_lora": False, "image_style_lora_name": "",
        "image_style_lora_strength": 0.0,
        "image_fallback_preset": "final_output", "image_output_dir": "/tmp/test",
        "image_max_batch_size": 1, "image_single_task_lock": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── safety filter ───────────────────────────────────────────────────────

class SafetyFilterTests(unittest.TestCase):
    def test_blocks_r18_keyword(self):
        blocked, _ = _check_blocked("画一张 R18 图")
        self.assertTrue(blocked)

    def test_blocks_porn_keyword(self):
        blocked, _ = _check_blocked("porn image")
        self.assertTrue(blocked)

    def test_blocks_nsfw_keyword(self):
        blocked, _ = _check_blocked("make a nsfw picture")
        self.assertTrue(blocked)

    def test_allows_normal_request(self):
        blocked, _ = _check_blocked("夏目安安头像，蓝色雨夜氛围")
        self.assertFalse(blocked)

    def test_allows_portrait_request(self):
        blocked, _ = _check_blocked("1girl, portrait, gentle smile")
        self.assertFalse(blocked)


# ── workflow patching ──────────────────────────────────────────────────

class WorkflowPatchTests(unittest.TestCase):
    def test_patch_does_not_mutate_original(self):
        original = copy.deepcopy(_ANIMA_ENHANCED)
        spec = ImagePromptSpec(positive_prompt="masterpiece, 1girl", negative_prompt="bad hands")
        cfg = _make_fake_config()
        patched = patch_workflow(original, spec, cfg)
        self.assertEqual(original["4"]["inputs"]["text"], "masterpiece, best quality, score_7, safe, 1girl, natsume_anan")
        self.assertEqual(patched["4"]["inputs"]["text"], "masterpiece, 1girl")

    def test_positive_prompt_patched(self):
        spec = ImagePromptSpec(positive_prompt="1girl, blue hair", negative_prompt="bad")
        cfg = _make_fake_config()
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["4"]["inputs"]["text"], "1girl, blue hair")

    def test_negative_prompt_patched(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="extra fingers")
        cfg = _make_fake_config()
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["5"]["inputs"]["text"], "extra fingers")

    def test_seed_patched_when_provided(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad", seed=42)
        cfg = _make_fake_config()
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["7"]["inputs"]["seed"], 42)

    def test_dimensions_patched(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad", width=512, height=768)
        cfg = _make_fake_config()
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["6"]["inputs"]["width"], 512)
        self.assertEqual(patched["6"]["inputs"]["height"], 768)

    def test_save_prefix_changed(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad")
        cfg = _make_fake_config()
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["16"]["inputs"]["filename_prefix"], "atri_anima")

    def test_client_id_patched(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad")
        cfg = _make_fake_config(comfyui_client_id="my-bot")
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["client_id"], "my-bot")


class LoRAPatchTests(unittest.TestCase):
    def test_character_lora_disabled_by_default(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad")
        cfg = _make_fake_config(image_use_character_lora=False, image_character_lora_name="x.safetensors", image_character_lora_strength=0.8)
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["11"]["inputs"]["strength_model"], 0.0)

    def test_style_lora_disabled_by_default(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad")
        cfg = _make_fake_config(image_use_style_lora=False, image_style_lora_name="y.safetensors", image_style_lora_strength=0.5)
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["12"]["inputs"]["strength_model"], 0.0)

    def test_character_lora_enabled_when_configured(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad")
        cfg = _make_fake_config(image_use_character_lora=True, image_character_lora_name="v3.safetensors", image_character_lora_strength=0.7)
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertEqual(patched["11"]["inputs"]["lora_name"], "v3.safetensors")
        self.assertEqual(patched["11"]["inputs"]["strength_model"], 0.7)

    def test_lora_not_deleted_when_disabled(self):
        spec = ImagePromptSpec(positive_prompt="1girl", negative_prompt="bad")
        cfg = _make_fake_config()
        patched = patch_workflow(_ANIMA_ENHANCED, spec, cfg)
        self.assertIn("11", patched)
        self.assertIn("12", patched)


class NodeDetectionTests(unittest.TestCase):
    def test_finds_positive_node(self):
        nid, node = _find_positive_node(_ANIMA_ENHANCED)
        self.assertEqual(nid, "4")
        self.assertIn("masterpiece", node["inputs"]["text"])

    def test_finds_negative_node(self):
        nid, node = _find_negative_node(_ANIMA_ENHANCED)
        self.assertEqual(nid, "5")
        self.assertIn("worst quality", node["inputs"]["text"])

    def test_finds_lora_nodes(self):
        self.assertEqual(len(_find_lora_nodes(_ANIMA_ENHANCED)), 2)

    def test_finds_seed_node(self):
        nid, node = _find_seed_node(_ANIMA_ENHANCED)
        self.assertIsNotNone(nid)
        self.assertIn("seed", node["inputs"])
        self.assertIn("steps", node["inputs"])

    def test_finds_dimensions_node(self):
        nid, node = _find_dimensions_node(_ANIMA_ENHANCED)
        self.assertIsNotNone(nid)
        self.assertIn("width", node["inputs"])

    def test_finds_save_prefix_node(self):
        nid, node = _find_save_prefix_node(_ANIMA_ENHANCED)
        self.assertIsNotNone(nid)
        self.assertIn("filename_prefix", node["inputs"])

    def test_loads_workflow_with_utf8_bom(self):
        """Workflow JSON with UTF-8 BOM must be parseable."""
        import json
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8-sig"
        )
        try:
            json.dump({"1": {"class_type": "Test"}}, tmp)
            tmp.close()
            wf = load_workflow(tmp.name)
            self.assertIsInstance(wf, dict)
            self.assertIn("1", wf)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_loads_wrapped_api_workflow(self):
        """Real API JSON with {'prompt': {nodes}, 'client_id': '...'} must be unwrapped."""
        import json
        import tempfile
        wrapped = {
            "prompt": {
                "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": "masterpiece, 1girl"}},
                "7": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20, "cfg": 4.0}},
            },
            "client_id": "test-client",
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(wrapped, tmp)
            tmp.close()
            wf = load_workflow(tmp.name)
            self.assertIn("4", wf)
            self.assertIn("7", wf)
            self.assertEqual(wf["4"]["class_type"], "CLIPTextEncode")
            self.assertEqual(wf["7"]["inputs"]["seed"], 42)
            # 'prompt' should NOT be a top-level key after unwrapping
            self.assertNotIn("prompt", wf)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_wrapped_workflow_does_not_leak_client_id_into_prompt(self):
        """After unwrapping, workflow must NOT contain 'client_id' (it goes in the top-level payload)."""
        import json
        import tempfile
        wrapped = {
            "prompt": {
                "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl"}},
            },
            "client_id": "from-api-json",
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(wrapped, tmp)
            tmp.close()
            wf = load_workflow(tmp.name)
            self.assertIn("4", wf)
            self.assertNotIn("client_id", wf)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def test_loads_flat_workflow_still_works(self):
        """Flat node dict (no 'prompt' wrapper) must still work — backward compat."""
        import json
        import tempfile
        flat = {"1": {"class_type": "Test", "inputs": {}}}
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(flat, tmp)
            tmp.close()
            wf = load_workflow(tmp.name)
            self.assertIn("1", wf)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


# ── /image command behavior ────────────────────────────────────────────

class ImageCommandDisabledTests(unittest.TestCase):
    def setUp(self):
        self._old_config = config_module.config

    def tearDown(self):
        config_module.config = self._old_config

    def _set(self, **overrides):
        new_dict = {}
        for fn in self._old_config.__dataclass_fields__:
            new_dict[fn] = getattr(self._old_config, fn)
        new_dict.update(overrides)
        if "admin_qq_ids" in overrides and not isinstance(new_dict["admin_qq_ids"], frozenset):
            new_dict["admin_qq_ids"] = frozenset(new_dict["admin_qq_ids"])
        config_module.config = SimpleNamespace(**new_dict)
        # Also patch the module-level reference in image.py
        import src.commands.image as img_mod
        import src.config as cfg_mod
        img_mod.config = cfg_mod.config

    def test_image_disabled(self):
        self._set(image_enable=False)
        result = image_cmd.image_reply("test", SimpleNamespace(uid="123"))
        self.assertIn("未启用", result)

    def test_image_admin_only_non_admin(self):
        self._set(image_enable=True, image_admin_only=True, admin_qq_ids=frozenset({"999"}))
        result = image_cmd.image_reply("test", SimpleNamespace(uid="123"))
        self.assertIn("管理员", result)

    def test_image_empty_input(self):
        self._set(image_enable=True, image_admin_only=False, comfyui_workflow_api_path="/nonexistent/path.json")
        result = image_cmd.image_reply("", SimpleNamespace(uid="123"))
        self.assertIn("用法", result)


# ── OneBot image URI ───────────────────────────────────────────────────

class OneBotImageUriTests(unittest.TestCase):
    def test_file_uri_conversion(self):
        p = Path("/tmp/test_output.png")
        uri = p.resolve().as_uri()
        self.assertTrue(uri.startswith("file:///"))
        self.assertIn("test_output.png", uri)


# ── Chat tool boundary ─────────────────────────────────────────────────

class ChatToolBoundaryTests(unittest.TestCase):
    def test_ordinary_chat_does_not_expose_image_tool(self):
        from src.chat import chat_service
        tool_names = [t["function"]["name"] for t in chat_service.chat_tools_for_text("画一张图")]
        self.assertNotIn("generate_image", tool_names)

    def test_supported_tool_names_has_no_image(self):
        from src.chat import chat_service
        for name in chat_service.SUPPORTED_TOOL_NAMES:
            self.assertNotIn("image", name.lower())
            self.assertNotIn("generate", name.lower())


# ── ComfyUI prompt sanitize ────────────────────────────────────────────

class ComfyUISanitizeTests(unittest.TestCase):
    def test_sanitize_filters_non_node_fields(self):
        workflow = {
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl"}},
            "client_id": "bad-inside-prompt",
            "metadata": {"x": 1},
            "stray_string": "hello",
        }
        clean = _sanitize_prompt_for_comfyui(workflow)
        self.assertIn("4", clean)
        self.assertNotIn("client_id", clean)
        self.assertNotIn("metadata", clean)
        self.assertNotIn("stray_string", clean)

    def test_sanitize_keeps_all_real_nodes(self):
        workflow = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "a.safetensors"}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl"}},
            "7": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20}},
        }
        clean = _sanitize_prompt_for_comfyui(workflow)
        self.assertEqual(len(clean), 3)
        self.assertIn("1", clean)
        self.assertIn("4", clean)
        self.assertIn("7", clean)

    def test_sanitize_returns_empty_for_empty_dict(self):
        self.assertEqual(_sanitize_prompt_for_comfyui({}), {})

    def test_sanitize_skips_nodes_missing_class_type(self):
        workflow = {
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl"}},
            "99": {"inputs": {"filename_prefix": "out"}},  # no class_type
        }
        clean = _sanitize_prompt_for_comfyui(workflow)
        self.assertIn("4", clean)
        self.assertNotIn("99", clean)


if __name__ == "__main__":
    unittest.main()
