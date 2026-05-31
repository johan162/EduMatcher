#!/bin/bash
#
# MkDocs Build and Deployment Script
# Usage:
#   ./mkdocs.sh serve    - Start local dev server
#   ./mkdocs.sh build    - Build static site
#   ./mkdocs.sh deploy   - Deploy to GitHub Pages
#   ./mkdocs.sh clean    - Remove built site

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

# Ensure docs dependencies are installed
ensure_deps() {
    echo "Checking documentation dependencies..."
    
    # Activate virtual environment if it exists and we're not already in one
    if [ -z "${VIRTUAL_ENV:-}" ] && [ -d "${PROJECT_ROOT}/.venv" ]; then
        echo "Activating virtual environment..."
        source "${PROJECT_ROOT}/.venv/bin/activate"
    fi
    
    if ! python -c "import mkdocs" 2>/dev/null; then
        echo "Installing documentation dependencies..."
        pip install -e ".[docs]"
    fi
}

# Serve documentation locally
serve_docs() {
    ensure_deps
    echo "Starting MkDocs development server..."
    echo "Documentation will be available at http://127.0.0.1:8000"
    mkdocs serve
}

# Build documentation
build_docs() {
    ensure_deps
    echo "Building documentation..."
    
    # Create symlink for CHANGELOG if it doesn't exist
    if [ ! -L "docs/CHANGELOG.md" ]; then
        ln -sf ../CHANGELOG.md docs/CHANGELOG.md
        echo "Created symlink: docs/CHANGELOG.md -> ../CHANGELOG.md"
    fi
    
    # Build without strict mode to allow external links
    mkdocs build
    echo "Documentation built successfully in site/"
}

# Deploy to GitHub Pages
deploy_docs() {
    ensure_deps
    echo "Deploying documentation to GitHub Pages..."
    
    # Create symlink for CHANGELOG if it doesn't exist
    if [ ! -L "docs/CHANGELOG.md" ]; then
        ln -sf ../CHANGELOG.md docs/CHANGELOG.md
        echo "Created symlink: docs/CHANGELOG.md -> ../CHANGELOG.md"
    fi
    
    # Deploy using mkdocs gh-deploy
    mkdocs gh-deploy --force --message "Deploy documentation [ci skip]"
    echo "Documentation deployed to GitHub Pages"
}

# Clean built documentation
clean_docs() {
    echo "Cleaning built documentation..."
    rm -rf site/
    
    # Remove CHANGELOG symlink if it exists
    if [ -L "docs/CHANGELOG.md" ]; then
        rm docs/CHANGELOG.md
        echo "Removed symlink: docs/CHANGELOG.md"
    fi
    
    echo "Documentation cleaned"
}

# Main script logic
case "${1:-}" in
    serve)
        serve_docs
        ;;
    build)
        build_docs
        ;;
    deploy)
        deploy_docs
        ;;
    clean)
        clean_docs
        ;;
    --help|-h)
        echo "Usage: $0 {serve|build|deploy|clean}"
        echo ""
        echo "Commands:"
        echo "  serve   - Start local development server at http://127.0.0.1:8000"
        echo "  build   - Build static documentation site to site/"
        echo "  deploy  - Deploy documentation to GitHub Pages"
        echo "  clean   - Remove built site and temporary files" 
        exit " --help |-h - Print this help message and exit"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Usage: $0 {serve|build|deploy|clean}"
        exit 1
        ;;
esac
