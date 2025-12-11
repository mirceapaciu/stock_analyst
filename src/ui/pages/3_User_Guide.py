"""Streamlit page for displaying the user guide."""

import streamlit as st
import sys
from pathlib import Path

# Add src directory to Python path
# Resolve __file__ first to handle any .. components, then go up to src/
src_path = Path(__file__).resolve().parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Check authentication first
from utils.auth import check_password
if not check_password():
    st.stop()  # Stop execution if not authenticated

st.set_page_config(page_title="User Guide", page_icon="📖", layout="wide")

st.title("📖 User Guide")

# Get the path to the user guide markdown file
# From src/ui/pages/ -> go up to project root -> docs/USER_GUIDE.md
project_root = src_path.parent
user_guide_path = project_root / "docs" / "USER_GUIDE.md"

if user_guide_path.exists():
    # Read and display the markdown content
    with open(user_guide_path, "r", encoding="utf-8") as f:
        guide_content = f.read()
    
    st.markdown(guide_content)
else:
    st.error(f"User guide not found at: {user_guide_path}")
    st.info("Please ensure the user guide file exists at `docs/USER_GUIDE.md`")

