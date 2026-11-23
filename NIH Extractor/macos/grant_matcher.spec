import os, sys, tomllib
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = os.path.dirname(SPECPATH)
sys.path.insert(0, root)
version = tomllib.load(open(os.path.join(root, "pyproject.toml"), "rb"))["project"]["version"]
st_datas, st_binaries, st_hidden = collect_all("streamlit")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[root],
    binaries=st_binaries,
    # collect_all does not pick up term_rarity.json, so it is listed by hand.
    datas=st_datas + copy_metadata("streamlit") + [(os.path.join(root, "nih_grant_matcher", "term_rarity.json"), "nih_grant_matcher"), (os.path.join(root, "streamlit_app.py"), ".")],
    hiddenimports=st_hidden + collect_submodules("nih_grant_matcher") + ["pandas"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Grant Matcher", console=False, target_arch="arm64", codesign_identity=os.environ.get("CODESIGN_IDENTITY"))
coll = COLLECT(exe, a.binaries, a.datas, name="Grant Matcher")
app = BUNDLE(
    coll,
    name="Grant Matcher.app",
    bundle_identifier="net.matherly.grant-matcher",
    version=version,
    info_plist={"CFBundleShortVersionString": version, "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True},
)
