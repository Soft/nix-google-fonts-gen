import logging
import hashlib
import re

from pathlib import Path
from pipes import quote
from typing import Iterable, Tuple, Optional, Set
from unidecode import unidecode

from nix_google_fonts_gen.repository import Family, Font, families

FONTS_REPO_URL = "https://github.com/google/fonts"

DERIVATION_TEMPLATE = """
{{ lib, stdenv, fetchurl }}:

stdenv.mkDerivation rec {{
  name = "{name}-${{version}}";
  version = "{version}";

  phases = [ "unpackPhase" "installPhase" ];

  srcs = [
{sources}
  ];

  unpackPhase = ''
    for font in $srcs; do
      cp "$font" "$(echo "$font" | cut -d- -f2-)"
    done
  '';

  installPhase = ''
{install}
  '';

  meta = with lib; {{
    description = "{description}";
    license = {license};
    platforms = platforms.all;
  }};
}}
""".lstrip(
    "\n"
)

FETCHER_TEMPLATE = """
    (fetchurl {{
      url = "{url}";
      name = "{name}";
      sha256 = "{hash}";
    }})
""".strip(
    "\n"
)

INSTALL_TEMPLATE = """
     install -Dm644 {file} $out/share/fonts{type}/{file}
""".strip(
    "\n"
)

INDEX_TEMPLATE = """
self: super:

{{
{packages}
}}
""".lstrip(
    "\n"
)

PACKAGE_TEMPLATE = """
    google-fonts-{package} = super.callPackage ./pkgs/{package} {{}};
""".strip(
    "\n"
)

LICENSE_MAP = {
    "UFL": "licenses.ufl",
    "OFL": "licenses.ofl",
    "APACHE2": "licenses.asl20",
}


def create_overlay(repository: Path, overlay: Path):
    packages: Set[str] = set()
    for family in families(repository):
        package = package_derivation(repository, family)
        if package is not None:
            name, derivation = package
            if name in packages:
                logging.warning("Duplicate font: %s", name)
                continue
            packages.add(name)
            dir = overlay / "pkgs" / name
            dir.mkdir(parents=True, exist_ok=True)
            with open(dir / "default.nix", "w") as handle:
                handle.write(derivation)
            logging.info("Wrote derivation for %s", family.meta.name)
    with open(overlay / "default.nix", "w") as handle:
        handle.write(package_index(packages))
    logging.info("Created %d derivations", len(packages))


def package_derivation(repository: Path, family: Family) -> Optional[Tuple[str, str]]:
    """Return nix expression for font family"""
    name = package_name(family)
    sources = "\n".join(font_fetcher(repository, font) for font in family.fonts)
    install = "\n".join(font_installer(font) for font in family.fonts)
    version = family.latest_change.strftime("%Y-%m-%d-%H%M%S")
    description = sanitize_string(family.meta.name)
    license = LICENSE_MAP.get(family.meta.license, None)
    if license is not None:
        return (
            name,
            DERIVATION_TEMPLATE.format(
                name=name,
                version=version,
                sources=sources,
                install=install,
                description=description,
                license=license,
            ),
        )
    else:
        logging.error("Unknown license: %s", license)


def package_index(packages: Iterable[str]) -> str:
    packages = "\n".join(
        PACKAGE_TEMPLATE.format(package=package) for package in sorted(packages)
    )
    return INDEX_TEMPLATE.format(packages=packages)


def package_name(family: Family) -> str:
    """Return sanitized font family name for use in package name"""
    return re.sub("[^a-z0-9]+", "-", unidecode(family.meta.name.lower()))


def sanitize_string(string: str) -> str:
    return string


def font_fetcher(repository: Path, font: Font) -> str:
    """Return fetcher expression for a font file"""
    url = font_url(repository, font).replace("[", "%5B").replace("]", "%5D")
    filename = font.path.name.replace("[", "_").replace("]", "_")
    hash = sha256_hex(font.path)
    return FETCHER_TEMPLATE.format(url=url, name=filename, hash=hash)


def font_installer(font: Font) -> str:
    """Return command for installing font file"""
    filename = font.path.name.replace("[", "_").replace("]", "_")
    ext = font.path.suffix.lower()
    if ext == ".ttf":
        type = "/truetype"
    elif ext == ".otf":
        type = "/opentype"
    else:
        logging.warning("Unknown font type: %s", filename)
        type = ""
    return INSTALL_TEMPLATE.format(file=quote(filename), type=type)


def font_url(repository: Path, font: Font) -> str:
    """Return URL for a font file"""
    relpath = font.path.relative_to(repository)
    return f"{FONTS_REPO_URL}/blob/{font.commit}/{relpath}?raw=true"


def sha256_hex(path: Path) -> str:
    """Return sha256 hash for a file"""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        hasher.update(handle.read())
    return hasher.hexdigest()
