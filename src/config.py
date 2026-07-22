"""
Exposure Analytics - configuration and path resolution.

Mirrors the global-building-forecast / building-regulations-CBA conventions:
config.yaml (UTF-8), DATA_ROOT auto-detection (env -> config -> Colab Drive
-> Windows drive letters), shared Source Data (WB boundaries, GHSL) resolved
from the sibling "Global Building Forecast" project.
"""

import os
import sys
import warnings

import yaml

IN_COLAB = 'google.colab' in sys.modules

EQUAL_AREA_CRS = 'ESRI:54009'   # Mollweide (all area math)
DISPLAY_CRS = 'EPSG:4326'


def _find_config():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cand = os.path.join(here, 'config.yaml')
    return cand if os.path.exists(cand) else None


def load_config():
    path = _find_config()
    if path:
        # explicit utf-8: Windows' default cp1252 mojibakes accented names
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


CFG = load_config()
COUNTRY_ISO = str(CFG.get('country_iso', 'MAR'))

_PROJECT_NAMES = ["Exposure Analytics"]


def _detect_data_root():
    env_root = os.environ.get('DATA_ROOT')
    if env_root and os.path.isdir(env_root):
        return env_root
    cfg_root = CFG.get('data_root')
    if cfg_root and os.path.isdir(str(cfg_root)):
        return str(cfg_root)
    if IN_COLAB:
        for nm in _PROJECT_NAMES:
            p = f"/content/drive/MyDrive/World Bank/{nm}"
            if os.path.isdir(p):
                return p
    for drive_letter in ['G', 'D', 'E', 'F', 'H']:
        for nm in _PROJECT_NAMES:
            p = f"{drive_letter}:/My Drive/World Bank/{nm}"
            if os.path.isdir(p):
                return p
    for nm in _PROJECT_NAMES:
        p = os.path.expanduser(f"~/My Drive/World Bank/{nm}")
        if os.path.isdir(p):
            return p
    warnings.warn('DATA_ROOT could not be auto-detected. Create '
                  '"World Bank/Exposure Analytics" on the Drive or set '
                  'DATA_ROOT / config.yaml data_root.')
    return None


DATA_ROOT = _detect_data_root()
WB_ROOT = os.path.dirname(os.path.normpath(DATA_ROOT)) if DATA_ROOT else None
FORECAST_PROJECT_DIR = (os.path.join(WB_ROOT, 'Global Building Forecast')
                        if WB_ROOT else None)

SOURCE_DIR = os.path.join(DATA_ROOT, 'Source Data') if DATA_ROOT else None
OUTPUTS_DIR = os.path.join(DATA_ROOT, 'Outputs') if DATA_ROOT else None
FIGURES_DIR = os.path.join(DATA_ROOT, 'Figures') if DATA_ROOT else None


def _first_existing(cands):
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return next((c for c in cands if c), None)


_forecast_source = (os.path.join(FORECAST_PROJECT_DIR, 'Source Data')
                    if FORECAST_PROJECT_DIR else None)
_source_candidates = [d for d in (SOURCE_DIR, _forecast_source) if d]


def _resolve_shared_subdir(sub):
    if not _source_candidates:
        return None
    return _first_existing([os.path.join(s, sub) for s in _source_candidates])


BOUNDARIES_DIR = _resolve_shared_subdir('Boundaries')
ADM0_PATH = (os.path.join(BOUNDARIES_DIR,
                          'World Bank Official Boundaries - Admin 0_all_layers.gpkg')
             if BOUNDARIES_DIR else None)
ADM1_PATH = (os.path.join(BOUNDARIES_DIR,
                          'World Bank Official Boundaries - Admin 1.gpkg')
             if BOUNDARIES_DIR else None)

GHSL_DIR = _resolve_shared_subdir('GHSL')

# GBA / Overture extraction outputs from the sibling forecast project
FORECAST_TRAINING_DIR = (os.path.join(FORECAST_PROJECT_DIR, 'Training')
                         if FORECAST_PROJECT_DIR else None)
