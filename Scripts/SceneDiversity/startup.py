"""Install reversible rendering profile, editor bridge and scene-only runtime."""
from pathlib import Path
import unreal

DIVERSITY_STARTUP_ROOT = Path(unreal.Paths.project_dir()).resolve()
exec((DIVERSITY_STARTUP_ROOT / 'Scripts/ScenePerformance/startup.py').read_text(encoding='utf-8-sig'))
scene_start('balanced')
exec((DIVERSITY_STARTUP_ROOT / 'Scripts/SceneDiversity/runtime.py').read_text(encoding='utf-8-sig'), SCOPE, SCOPE)
SCOPE['diversity_install']()
