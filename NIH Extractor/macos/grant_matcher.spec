import os, re, sys, tomllib
from importlib import metadata
from packaging.requirements import Requirement
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = os.path.dirname(SPECPATH)
sys.path.insert(0, root)
# macos/rehearse-update.sh sets the three variables to build throwaway versions under another bundle ID and key.
version = os.environ.get("GRANT_MATCHER_VERSION") or tomllib.load(open(os.path.join(root, "pyproject.toml"), "rb"))["project"]["version"]
key_file = os.path.join(SPECPATH, "sparkle-public-key.txt")
public_key = os.environ.get("SPARKLE_PUBLIC_KEY") or (open(key_file).read().strip() if os.path.isfile(key_file) else "")
if not public_key:
    raise SystemExit(f"{key_file} is missing and SPARKLE_PUBLIC_KEY is not set. An app without the update key can never be updated.")
st_datas, st_binaries, st_hidden = collect_all("streamlit")


def licence_files() -> list[tuple[str, str]]:
    # Every package the app ships, found by walking the requirements of the three it imports.
    found, todo = {}, ["streamlit", "pandas", "pywebview"]
    while todo:
        name = re.sub(r"[-_.]+", "-", todo.pop()).lower()
        if name in found:
            continue
        try:
            found[name] = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        for line in found[name].requires or []:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate():
                todo.append(requirement.name)
    datas = []
    for name, dist in found.items():
        for file in dist.files or []:
            parts = str(file).split(".dist-info/", 1)
            if len(parts) == 2 and re.search(r"LICEN[CS]E|NOTICE|COPYING|AUTHORS", parts[1], re.I):
                datas.append((str(dist.locate_file(file)), os.path.join("licenses", name, os.path.dirname(parts[1]))))
    # Streamlit's wheel carries neither file, so build.sh fetches both from its repository.
    fetched = os.path.join(SPECPATH, "build", "licenses", "streamlit")
    for file in ("LICENSE", "NOTICES"):
        if not os.path.isfile(os.path.join(fetched, file)):
            raise SystemExit(f"{fetched}/{file} is missing. Build with macos/build.sh, which fetches it.")
        datas.append((os.path.join(fetched, file), os.path.join("licenses", "streamlit")))
    return datas

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[root],
    binaries=st_binaries,
    # collect_submodules gathers code only, so the data files that config.py and ui/tour.py read beside themselves are listed by hand, each by name so that a stray file is not shipped.
    datas=st_datas + copy_metadata("streamlit") + [(os.path.join(root, "nih_grant_matcher", "term_rarity.json"), "nih_grant_matcher"), (os.path.join(root, "streamlit_app.py"), ".")]
    + [(os.path.join(root, "nih_grant_matcher", "ui", "vendor", f), os.path.join("nih_grant_matcher", "ui", "vendor")) for f in ("driver.js.iife.js", "driver.css", "driver.js.LICENSE")]
    + [(os.path.join(root, "nih_grant_matcher", "ui", "vendor", "driver.js.LICENSE"), os.path.join("licenses", "driver.js"))] + licence_files(),
    hiddenimports=st_hidden + collect_submodules("nih_grant_matcher") + ["pandas"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Grant Matcher", console=False, target_arch="arm64", codesign_identity=os.environ.get("CODESIGN_IDENTITY"))
coll = COLLECT(exe, a.binaries, a.datas, name="Grant Matcher")
app = BUNDLE(
    coll,
    name="Grant Matcher.app",
    # Rendered from icon.svg. PyInstaller turns the PNG into an .icns file with Pillow, which Streamlit installs.
    icon=os.path.join(SPECPATH, "icon.png"),
    bundle_identifier=os.environ.get("GRANT_MATCHER_BUNDLE_ID") or "net.matherly.grant-matcher",
    version=version,
    # Sparkle reads SUVerifyUpdateBeforeExtraction from the installed app, so a later release cannot add it for the users of this one.
    info_plist={"CFBundleShortVersionString": version, "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True, "CFBundleVersion": version, "SUFeedURL": "https://github.com/jrmatherly/Research-Grant-Finder-Agent/releases/latest/download/appcast.xml", "SUPublicEDKey": public_key, "SUEnableAutomaticChecks": True, "SUVerifyUpdateBeforeExtraction": True},
)
