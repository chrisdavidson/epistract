#!/bin/bash
set -e

INSTALL_ALL=false
for arg in "$@"; do
  case "$arg" in
    --all) INSTALL_ALL=true ;;
  esac
done

echo "=== epistract setup ==="
echo ""

# Check Python >= 3.11
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
  echo "ERROR: Python >= 3.11 required, found $PYTHON_VERSION"
  exit 1
fi
echo "Python $PYTHON_VERSION"

# Check/install sift-kg
if ! python3 -c "import sift" 2>/dev/null; then
  echo "sift-kg not found, installing..."
  uv pip install sift-kg 2>/dev/null || pip install sift-kg
fi
SIFT_VERSION=$(python3 -c "import importlib.metadata; print(importlib.metadata.version('sift-kg'))" 2>/dev/null || echo "unknown")
echo "sift-kg $SIFT_VERSION"

# Check/install RDKit
if python3 -c "from rdkit import Chem" 2>/dev/null; then
  RDKIT_VERSION=$(python3 -c "from rdkit import rdBase; print(rdBase.rdkitVersion)" 2>/dev/null || echo "available")
  echo "RDKit $RDKIT_VERSION"
elif [ "$INSTALL_ALL" = true ]; then
  echo "Installing RDKit..."
  uv pip install rdkit-pypi 2>/dev/null || pip install rdkit-pypi
  echo "RDKit installed"
else
  echo "RDKit not available (optional, install with: uv pip install rdkit-pypi  or re-run with --all)"
fi

# Check/install Biopython
if python3 -c "from Bio import Seq" 2>/dev/null; then
  BIO_VERSION=$(python3 -c "import importlib.metadata; print(importlib.metadata.version('biopython'))" 2>/dev/null || echo "available")
  echo "Biopython $BIO_VERSION"
elif [ "$INSTALL_ALL" = true ]; then
  echo "Installing Biopython..."
  uv pip install biopython 2>/dev/null || pip install biopython
  echo "Biopython installed"
else
  echo "Biopython not available (optional, install with: uv pip install biopython  or re-run with --all)"
fi

echo ""
echo "Setup complete."
