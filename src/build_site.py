"""Package only the dashboard and its assets for GitHub Pages."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
DIST.mkdir(exist_ok=True)
shutil.copy2(ROOT/'index.html',DIST/'index.html')
shutil.copytree(ROOT/'assets',DIST/'assets',dirs_exist_ok=True)
(DIST/'.nojekyll').write_text('')
print(DIST)
