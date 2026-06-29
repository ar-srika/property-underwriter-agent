import os
import sys
from mcp.server.fastmcp import FastMCP
from pypdf import PdfReader

mcp = FastMCP("property-underwriter-mcp")

# Helper to find file in workspace or project
def find_file(filename: str) -> str:
    # Try current directory, project directory, parent directories
    candidates = [
        filename,
        os.path.join("property-underwriter", filename),
        os.path.join("app", filename),
        os.path.join("..", filename),
        os.path.join("..", "property-underwriter", filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return filename

@mcp.tool()
def get_fire_protection_standards() -> str:
    """Retrieve the standard fire protection regulations, safety requirements, and hydrant distances for underwriting."""
    path = find_file("fire_protection_standards.txt")
    if not os.path.exists(path):
        return (
            "Standard: Fire hydrant must be within 1000 feet of the property.\n"
            "Standard: Automatic wet sprinkler systems are required for all wood-framed structures over 3 stories.\n"
            "Standard: Fire extinguishers must be inspected annually and mounted every 75 feet."
        )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool()
def get_underwriting_guidelines() -> str:
    """Retrieve the corporate underwriting guidelines, restricted property types, and safety policy boundaries."""
    path = find_file("underwriting_guidelines.txt")
    if not os.path.exists(path):
        return (
            "Guideline: Restricted properties include those with knob-and-tube wiring or active wood stove heating.\n"
            "Guideline: Minimum acceptable building age without recent electrical update is 40 years.\n"
            "Guideline: Maximum acceptable risk score for auto-approval is 39."
        )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool()
def get_risk_scoring_matrix() -> str:
    """Retrieve the risk scoring weights, calculation matrix, and risk rating boundaries (Low/Medium/High)."""
    path = find_file("risk_scoring_matrix.txt")
    if not os.path.exists(path):
        return (
            "Scoring Matrix:\n"
            "Base Score: 50\n"
            "Hydrant > 1000 ft: +15 points\n"
            "No Sprinklers: +20 points\n"
            "Building Age > 40 years: +10 points\n"
            "Knob and Tube Wiring: +30 points\n"
            "Sprinkler System Present (Automatic Wet Pipe): -25 points\n"
            "Building Age < 5 years: -10 points\n"
            "Ratings:\n"
            "Score < 40: Low Risk (Auto-Approve)\n"
            "Score 40-75: Medium Risk (HITL review required)\n"
            "Score > 75: High Risk (Auto-Reject)"
        )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool()
def parse_property_questionnaire(file_path: str = "property_risk_questionnaire.pdf") -> str:
    """Parse and extract text/risk indicators from property_risk_questionnaire.pdf or a fallback questionnaire text file."""
    path = find_file(file_path)
    if not os.path.exists(path):
        # Return a mock property questionnaire if the file does not exist
        return (
            "Property Risk Questionnaire (Mocked Fallback)\n"
            "Policyholder Name: John Doe\n"
            "Address: 742 Evergreen Terrace\n"
            "Building Age: 45 years\n"
            "Sprinkler System: None\n"
            "Distance to Fire Hydrant: 1200 feet\n"
            "Wiring Type: Standard Copper (Updated 2015)\n"
            "Heating System: Central HVAC"
        )
    
    # Try reading as PDF
    if path.lower().endswith(".pdf"):
        try:
            reader = PdfReader(path)
            text = []
            for page in reader.pages:
                text.append(page.extract_text() or "")
            extracted = "\n".join(text)
            if extracted.strip():
                return extracted
        except Exception as e:
            return f"Error reading PDF: {e}. Falling back to default data."
            
    # Fallback to reading as text if not PDF or PDF parsing failed
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

if __name__ == "__main__":
    mcp.run()
