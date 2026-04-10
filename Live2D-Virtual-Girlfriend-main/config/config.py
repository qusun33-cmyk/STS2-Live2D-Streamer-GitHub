import os
import ast
import toml
from queue import Queue

from .provider_profiles import normalize_model_sections


def _resolve_path(base_dir, value):
    if not value:
        return value
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(base_dir, value))


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
config_path = os.environ.get("LIVE2D_CONFIG_PATH", os.path.join(project_root, "config.toml"))
config_path = os.path.abspath(_resolve_path(project_root, config_path))
config_dir = os.path.dirname(config_path)

with open(config_path, 'r', encoding='utf-8-sig') as f:
    config = toml.loads(f.read())
config = normalize_model_sections(config)

character_toml = _resolve_path(config_dir, config['character_toml'])
with open(character_toml, 'r', encoding='utf-8-sig') as f:
    character = toml.loads(f.read())

character_dir = os.path.dirname(character_toml)
character["live2d_model"] = _resolve_path(character_dir, character["live2d_model"])
if "ref_audio" in character:
    character["ref_audio"] = _resolve_path(character_dir, character["ref_audio"])
character["system_prompt"] = _resolve_path(character_dir, character["system_prompt"])
character["exp"] = _resolve_path(character_dir, character["exp"])

class Global:
    # 全局变量
    subtitle_lang = 'zh'
    happy = 5
    current_mouth_y = 0.0
    screenshot_t = 0
    exist = True
    send_text_thread = None
    sing_song_thread = None
    mcp_client = None
    asr_thread = None
    web_asr_thread = None
    received_photo = Queue()

    user_name: str
    character: dict
    auxiliary: dict
    required: dict
    providers: dict
    exp_queue: Queue

    character_toml = None
    device = None
    context_length = None
    save_memory_steps = None
    embedding = None
    memory_entity_top_k = None
    memory_entity_similarity_threshold = None
    memory_relationships_top_k = None
    memory_relationships_similarity_threshold = None
    memory_temporal_top_k = None
    memory_temporal_similarity_threshold = None
    niutrans_app_id = None
    niutrans_api_key = None
    your_voices = None
    other_voices = None
    verifier_threshold = None
    aggressiveness = None
    shot_word = None
    hot_word = None
    gsv_api2 = None
    kokoro_api = None
    rvc_url = None
    cut_length = None
    cut_sleep = None
    input_box = None
    always_screenshot = None
    initiative_wait_range = None
    exp_fadeout = None
    modelscope = None
    weblive2d = None
    rvc = None
    memory = None
    speaker_verifier = None
    sense_voice = None
    web_clear_audio = None
    web_audio_stream = None
    web_request_photo = None
    send_audio_text = None
    font = None
    animator1 = None
    animator2 = None
    func_queue1 = None
    func_queue2 = None
    model = None
    live2d_animator = None
    blink_animator = None
    eyeball_animator = None
    emotion_animator = None
    expression_animator = None
    appearance_animator = None
    win = None
    parts = None
    exp_params = None
    kokoro_client = None
    audio_queue = None
    func_queue3 = None
    my_agent = None
    sounds_player = None
    load_model = None
    bubble_widget = None
    sing = None
    baidu_api_key = None
    baidu_secret_key = None

setattr(Global, 'character', character)
for key, value in config.items():
    if key == 'hot_word':
        value = ast.literal_eval(value)
    if key == 'character_toml':
        value = character_toml
    setattr(Global, key, value)
