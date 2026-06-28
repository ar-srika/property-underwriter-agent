import datetime
import os
import re
import sys
import json

from mcp import StdioServerParameters
from google.adk import Agent, Context, Workflow
from google.adk.apps import App
from google.adk.workflow import node, START, Edge
from google.adk.events import RequestInput
from google.adk.tools import AgentTool, MCPToolset
from google.adk.models import Gemini

from .config import config

# Define MCP toolset to connect to our local MCP server
mcp_toolset = MCPToolset(
    connection_params=StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
    )
)

# Define sub-agents
compliance_agent = Agent(
    name="compliance_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Compliance Validator Agent. Your role is to inspect the property risk questionnaire "
        "and compare it against the compliance standards. Use your tools to fetch fire protection standards "
        "and underwriting guidelines. You must check for violations or high risk items, such as lack of sprinkler systems, "
        "distance to fire hydrant, or outdated wiring. Summarize your findings indicating which guidelines are met and which are breached."
    ),
    tools=[mcp_toolset]
)

scoring_agent = Agent(
    name="scoring_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Scoring Agent. Your task is to compute a risk score for the property. "
        "Use your tools to fetch the risk scoring matrix and parse the property risk questionnaire. "
        "Read the property details and the Compliance Agent's findings, then apply the scoring weights from the risk scoring matrix. "
        "Provide a structured scoring output, detailed list of key drivers, and suggest terms & conditions."
    ),
    tools=[mcp_toolset]
)

underwriter_orchestrator = Agent(
    name="underwriter_orchestrator",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Lead Underwriter Orchestrator. Your task is to analyze the property risk questionnaire "
        "and determine the risk profile of the property. "
        "Coordinate the assessment by: "
        "1. Invoking the Compliance Agent to check for compliance issues against fire protection standards and underwriting guidelines. "
        "2. Invoking the Scoring Agent to calculate the risk score and risk rating based on the scoring matrix. "
        "Combine the findings from both agents to formulate a comprehensive underwriting assessment. "
        "Always structure your final evaluation in detail. You MUST end your response with a valid JSON block enclosed in ```json ... ``` containing keys: "
        "'score' (number between 0 and 100), "
        "'risk_rating' (Low, Medium, or High), "
        "'key_drivers' (list of strings describing the positive or negative drivers), "
        "'risk_factors' (list of strings detailing critical risk factors), "
        "'terms_conditions' (list of strings of recommended underwriting conditions), "
        "and 'recommendation' (string explaining the decision summary)."
    ),
    tools=[
        AgentTool(agent=compliance_agent),
        AgentTool(agent=scoring_agent),
    ]
)

@node(rerun_on_resume=False)
async def security_checkpoint(ctx: Context, node_input: str):
    # Scrub PII
    scrubbed = node_input
    if config.pii_redaction_enabled:
        # Scrub email
        scrubbed = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[REDACTED_EMAIL]', scrubbed)
        # Scrub SSN
        scrubbed = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED_SSN]', scrubbed)
        # Scrub Phone
        scrubbed = re.sub(r'\b\d{3}-\d{3}-\d{4}\b', '[REDACTED_PHONE]', scrubbed)
        # Scrub policy holder name placeholder patterns if any
        scrubbed = re.sub(r'(?i)policyholder\s*name\s*[:=]\s*[^\n]+', 'Policyholder Name: [REDACTED_NAME]', scrubbed)

    # Prompt injection check
    if config.injection_detection_enabled:
        injection_keywords = ["ignore previous instructions", "system prompt", "override guidelines", "bypass rules"]
        for keyword in injection_keywords:
            if keyword in node_input.lower():
                ctx.state["security_error"] = f"Security Event: Prompt injection keyword '{keyword}' detected!"
                ctx.route = "security_event"
                # Structured JSON audit log
                print(json.dumps({
                    "severity": "CRITICAL",
                    "message": f"Prompt injection detected: {keyword}",
                    "timestamp": datetime.datetime.now().isoformat()
                }))
                return "Prompt injection detected!"

    # Domain-specific safety check: Prohibit knob-and-tube wiring hazards
    if "knob-and-tube" in node_input.lower() or "knob & tube" in node_input.lower():
        ctx.state["security_error"] = "Security Event: Prohibited knob-and-tube wiring detected."
        ctx.route = "security_event"
        print(json.dumps({
            "severity": "CRITICAL",
            "message": "Knob-and-tube wiring hazard detected.",
            "timestamp": datetime.datetime.now().isoformat()
        }))
        return "Prohibited wiring type!"

    ctx.state["scrubbed_questionnaire"] = scrubbed
    ctx.state["original_questionnaire"] = node_input
    ctx.route = "pass"
    
    # Structured JSON audit log
    print(json.dumps({
        "severity": "INFO",
        "message": "PII scrubbed successfully. Node input routed to orchestrator.",
        "timestamp": datetime.datetime.now().isoformat()
    }))
    return scrubbed

@node
async def security_event(ctx: Context):
    error_msg = ctx.state.get("security_error", "Unknown security breach.")
    ctx.state["status"] = "REJECTED_SECURITY"
    ctx.state["recommendation"] = f"Application rejected due to security policy violation: {error_msg}"
    print(json.dumps({
        "severity": "WARNING",
        "message": f"Security event finalized: {error_msg}",
        "timestamp": datetime.datetime.now().isoformat()
    }))
    return f"Security Failure: {error_msg}"

@node
async def decision_gate(ctx: Context, node_input: str):
    json_match = re.search(r'```json\s*(.*?)\s*```', node_input, re.DOTALL)
    score = 50.0
    rating = "Medium"
    drivers = []
    factors = []
    terms = []
    rec = node_input
    
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            score = float(data.get("score", 50.0))
            rating = data.get("risk_rating", "Medium")
            drivers = data.get("key_drivers", [])
            factors = data.get("risk_factors", [])
            terms = data.get("terms_conditions", [])
            rec = data.get("recommendation", "")
        except Exception as e:
            print(f"Error parsing JSON from orchestrator: {e}")
    else:
        score_match = re.search(r'(?i)(?:\bscore\b|\bpoints\b)\s*[:=]\s*(\d+(?:\.\d+)?)', node_input)
        rating_match = re.search(r'(?i)(?:\brating\b|\bclass\b)\s*[:=]\s*(High|Medium|Low|Borderline)', node_input)
        if score_match:
            score = float(score_match.group(1))
        if rating_match:
            rating = rating_match.group(1)

    ctx.state["preliminary_score"] = score
    ctx.state["risk_rating"] = rating
    ctx.state["key_drivers"] = drivers
    ctx.state["risk_factors"] = factors
    ctx.state["terms_conditions"] = terms
    ctx.state["recommendation"] = rec

    # Borderline zone: scores between 40 and 75 require manual underwriting review (HITL)
    if 40.0 <= score <= 75.0:
        ctx.route = "borderline"
        print(json.dumps({
            "severity": "WARNING",
            "message": f"Borderline score ({score}) requires HITL review.",
            "timestamp": datetime.datetime.now().isoformat()
        }))
    else:
        ctx.route = "auto"
        print(json.dumps({
            "severity": "INFO",
            "message": f"Score ({score}) categorized for auto decision.",
            "timestamp": datetime.datetime.now().isoformat()
        }))
    return node_input

@node(rerun_on_resume=True)
async def hitl_review(ctx: Context):
    user_response = ctx.resume_inputs.get("underwriter_approval")
    
    if user_response is None:
        # Pause the workflow and request input
        yield RequestInput(
            interrupt_id="underwriter_approval",
            message=(
                f"The risk assessment for this property is borderline (Score: {ctx.state.get('preliminary_score')}, "
                f"Rating: {ctx.state.get('risk_rating')}). Please review and provide your approval status (True/False)."
            ),
            response_schema=bool
        )
        return
        
    ctx.state["underwriter_notes"] = f"Underwriter reviewed and set approval to: {user_response}"
    ctx.state["status"] = "APPROVED_BY_UNDERWRITER" if user_response else "REJECTED_BY_UNDERWRITER"
    print(json.dumps({
        "severity": "INFO",
        "message": f"HITL review completed: {user_response}",
        "timestamp": datetime.datetime.now().isoformat()
    }))

@node
async def finalize_decision(ctx: Context):
    status = ctx.state.get("status")
    if not status:
        if ctx.state.get("preliminary_score", 0.0) < 40.0:
            status = "AUTO_APPROVED"
        else:
            status = "AUTO_REJECTED"
        ctx.state["status"] = status
        
    result = {
        "status": status,
        "risk_rating": ctx.state.get("risk_rating", "Unknown"),
        "overall_score": ctx.state.get("preliminary_score", 0.0),
        "key_drivers": ctx.state.get("key_drivers", []),
        "risk_factors": ctx.state.get("risk_factors", []),
        "terms_conditions": ctx.state.get("terms_conditions", []),
        "recommendation": ctx.state.get("recommendation", ""),
        "underwriter_notes": ctx.state.get("underwriter_notes", "")
    }
    
    print(json.dumps({
        "severity": "INFO",
        "message": f"Finalized risk assessment decision: {status}",
        "timestamp": datetime.datetime.now().isoformat()
    }))
    
    return json.dumps(result, indent=2)

# Build the workflow
workflow = Workflow(
    name="underwriting_workflow",
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=underwriter_orchestrator, route="pass"),
        Edge(from_node=security_checkpoint, to_node=security_event, route="security_event"),
        Edge(from_node=underwriter_orchestrator, to_node=decision_gate),
        Edge(from_node=decision_gate, to_node=hitl_review, route="borderline"),
        Edge(from_node=decision_gate, to_node=finalize_decision, route="auto"),
        Edge(from_node=hitl_review, to_node=finalize_decision),
        Edge(from_node=security_event, to_node=finalize_decision),
    ]
)

app = App(
    root_agent=workflow,
    name="app",
)
