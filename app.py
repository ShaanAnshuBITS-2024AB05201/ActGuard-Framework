import streamlit as st
import json, re, time, torch, requests
from simple_salesforce import Salesforce
from transformers import AutoModelForCausalLM, AutoTokenizer

st.set_page_config(page_title="ActGuard", page_icon="A", layout="wide")

# ============================================================
# SALESFORCE CONNECTION  (same org as the benchmark notebook)
# ============================================================
CLIENT_ID = "YOUR_SALESFORCE_CLIENT_ID"
CLIENT_SECRET = "YOUR_SALESFORCE_CLIENT_SECRET"
LOGIN_URL = "https://orgfarm-b9b632aee3-dev-ed.develop.my.salesforce.com/services/oauth2/token"
INSTANCE_URL = "https://orgfarm-b9b632aee3-dev-ed.develop.my.salesforce.com"

RESTRICTED_FIELD = "Status__c"   # custom restricted picklist
OPEN_FIELD = "Industry"          # standard UNrestricted picklist


@st.cache_resource(show_spinner=False)
def connect():
    r = requests.post(LOGIN_URL, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET})
    r.raise_for_status()
    return Salesforce(instance_url=INSTANCE_URL,
                      session_id=r.json()["access_token"])


def describe_account(_sf):
    """Live metadata pull. Layer 1's ground truth comes from here,
       not from a hardcoded dict."""
    desc = _sf.Account.describe()
    schema = {}
    for f in desc["fields"]:
        if f["type"] == "picklist":
            schema[f["name"]] = {
                "type": "picklist",
                "restricted": f.get("restrictedPicklist", False),
                "label": f["label"],
                "values": [v["value"] for v in f["picklistValues"] if v["active"]],
            }
        elif f["name"] in ("Description", "Name"):
            schema[f["name"]] = {"type": "string", "label": f["label"]}
    return schema


def get_demo_account(_sf):
    q = _sf.query("SELECT Id, Name FROM Account ORDER BY CreatedDate LIMIT 1")
    if q["totalSize"] == 0:
        rec = _sf.Account.create({"Name": "ActGuard Demo Account"})
        return rec["id"], "ActGuard Demo Account"
    return q["records"][0]["Id"], q["records"][0]["Name"]


def read_record(_sf, rec_id, fields):
    cols = ", ".join(["Id", "Name"] + fields)
    return _sf.query(f"SELECT {cols} FROM Account WHERE Id = '{rec_id}'")["records"][0]


# ============================================================
# ACTGUARD — three verdicts: PASS / BLOCK / ESCALATE
# ============================================================
def layer1_metadata(payload, schema):
    """Returns (verdict, code, reason) or None. Verdict: BLOCK | ESCALATE."""
    for field, value in payload.get("arguments", {}).items():
        spec = schema.get(field)
        if spec is None:
            return ("BLOCK", "INVALID_FIELD",
                    f"Field '{field}' is not defined on Account in this org.")

        if spec["type"] == "picklist" and value not in spec["values"]:
            if spec["restricted"]:
                return ("BLOCK", "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST",
                        f"`{value}` is not an active value for **{field}**, and "
                        f"this picklist is **Restricted**. The Salesforce API "
                        f"would reject this write outright. "
                        f"Active values: {', '.join(spec['values'])}.")
            return ("ESCALATE", "UNRESTRICTED_PICKLIST_NOVEL_VALUE",
                    f"`{value}` is not a defined value for **{field}**. This "
                    f"picklist is **Unrestricted**, so Salesforce will accept "
                    f"the write and store it on the record — with no error, no "
                    f"warning, and without adding it to the field's value set. "
                    f"The record and the schema will diverge silently.")
    return None


def extract_json(text):
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ============================================================
# LOCAL AGENT
# ============================================================
MODELS = {
    "Qwen2.5-1.5B-Instruct": "Qwen/Qwen2.5-1.5B-Instruct",
    "Qwen2.5-0.5B-Instruct": "Qwen/Qwen2.5-0.5B-Instruct",
}


@st.cache_resource(show_spinner=False)
def load_model(model_id):
    tok = AutoTokenizer.from_pretrained(model_id)
    mdl = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto")
    return tok, mdl


def build_tool_spec(schema):
    """The agent is told the field NAMES but never the allowed VALUES.
       That gap is where action-space hallucination originates."""
    fields = [RESTRICTED_FIELD, OPEN_FIELD, "Description"]
    listed = ", ".join(f for f in fields if f in schema or f == "Description")
    return f"""You have one tool:
  update_account(arguments)

Editable Account fields: {listed}

Reply with ONLY a JSON object. No prose. No markdown fences.
Example: {{"arguments": {{"{OPEN_FIELD}": "Banking"}}}}"""


def run_agent(tok, mdl, prompt, temperature, tool_spec):
    messages = [
        {"role": "system",
         "content": "You are a Salesforce Agentforce assistant. Convert the "
                    "user request into a tool call.\n" + tool_spec},
        {"role": "user", "content": prompt}]
    text = tok.apply_chat_template(messages, tokenize=False,
                                   add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(mdl.device)
    out = mdl.generate(**inputs, max_new_tokens=80,
                       do_sample=temperature > 0,
                       temperature=max(temperature, 0.01),
                       top_p=0.9, pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:],
                      skip_special_tokens=True)


def commit(sf, rec_id, args):
    """Real write to the real org."""
    t0 = time.time()
    try:
        sf.Account.update(rec_id, args)
        return True, None, (time.time() - t0) * 1000
    except Exception as e:
        return False, str(e)[:300], (time.time() - t0) * 1000


# ============================================================
# BOOT
# ============================================================
sf = connect()
if "schema" not in st.session_state:
    st.session_state.schema = describe_account(sf)
if "rec" not in st.session_state:
    st.session_state.rec = get_demo_account(sf)
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None
if "audit" not in st.session_state:
    st.session_state.audit = []

schema = st.session_state.schema
rec_id, rec_name = st.session_state.rec
demo_fields = [f for f in (RESTRICTED_FIELD, OPEN_FIELD) if f in schema]

with st.sidebar:
    st.markdown("## ActGuard")
    st.caption("Pre-commit firewall for tool-using LLM agents")
    st.markdown("---")
    label = st.selectbox("Agent LLM (local)", list(MODELS.keys()))
    model_id = MODELS[label]
    temp = st.slider("Temperature", 0.0, 1.5, 0.7, 0.1,
                     help="Raise to induce more hallucination.")
    st.markdown("---")
    guard_on = st.toggle("ActGuard enabled", value=True,
                         help="Turn OFF to let the agent write straight "
                              "to Salesforce, unmediated.")
    if not guard_on:
        st.error("Firewall bypassed. Agent writes commit directly.")
    st.markdown("---")
    st.markdown(f"**Org:** `orgfarm-b9b632aee3`")
    st.markdown(f"**Record:** `{rec_id}`")
    st.markdown(f"**Compute:** {'GPU' if torch.cuda.is_available() else 'CPU'}")
    if st.button("Refresh metadata from org"):
        st.session_state.schema = describe_account(sf)
        st.rerun()
    if st.button("Clear conversation"):
        st.session_state.messages, st.session_state.audit = [], []
        st.session_state.pending = None
        st.rerun()

st.markdown("# ActGuard")
st.caption("Not every bad write fails. The dangerous ones succeed quietly.")

# ------------------------------------------------------------
# LIVE ORG STATE — schema vs data
# ------------------------------------------------------------
live = read_record(sf, rec_id, demo_fields)
st.markdown(f"### Live org state — Account `{live['Name']}`")
cols = st.columns(len(demo_fields))
divergent = False

for col, fname in zip(cols, demo_fields):
    spec = schema[fname]
    current = live.get(fname)
    tag = "RESTRICTED" if spec["restricted"] else "UNRESTRICTED"
    with col:
        st.markdown(f"**{fname}** · {tag}")
        st.caption(f"Defined values ({len(spec['values'])}): "
                   f"{', '.join(spec['values'][:6])}"
                   f"{'…' if len(spec['values']) > 6 else ''}")
        if current is None:
            st.info("Record value: *(empty)*")
        elif current in spec["values"]:
            st.success(f"Record value: **{current}** IN value set")
        else:
            divergent = True
            st.error(f"Record value: **{current}** NOT in value set")

if divergent:
    st.warning("**Schema/data divergence detected.** This Account holds a "
               "picklist value that does not exist in the field's definition. "
               "`describe()` will never report it, reports will treat it as a "
               "distinct category, and no error was ever raised.")

st.markdown("---")

# ------------------------------------------------------------
# HUMAN-IN-THE-LOOP APPROVAL
# ------------------------------------------------------------
if st.session_state.pending:
    p = st.session_state.pending
    st.warning(f"**Human approval required** — `{p['code']}`")
    st.markdown(p["reason"])
    st.code(json.dumps(p["payload"], indent=2), language="json")
    st.markdown("**Salesforce would have committed this without asking. "
                "ActGuard is asking.**")

    a, b = st.columns(2)
    if a.button("Approve - write to Salesforce", use_container_width=True):
        ok, err, ms = commit(sf, rec_id, p["payload"]["arguments"])
        msg = (f"**APPROVED BY OPERATOR.** Written to Salesforce in {ms:.0f} ms. "
               f"Check the live org state above — the record now holds a value "
               f"that is not in the field's value set."
               if ok else f"REJECTED. Salesforce rejected the write: `{err}`")
        st.session_state.messages.append({"role": "assistant", "content": msg})
        st.session_state.audit.append({**p["log"], "outcome": "approved",
                                       "committed": ok})
        st.session_state.pending = None
        st.rerun()

    if b.button("Reject - discard action", use_container_width=True):
        st.session_state.messages.append({"role": "assistant", "content":
            "**REJECTED BY OPERATOR.** Nothing was written. Org unchanged."})
        st.session_state.audit.append({**p["log"], "outcome": "rejected"})
        st.session_state.pending = None
        st.rerun()

# ------------------------------------------------------------
# DEMO PROMPTS
# ------------------------------------------------------------
busy = bool(st.session_state.pending)
c1, c2, c3 = st.columns(3)
preset = None
if c1.button(f"Novel value -> {OPEN_FIELD} (unrestricted)",
             use_container_width=True, disabled=busy):
    preset = "Set this account's industry to Space Tourism"
if c2.button(f"Novel value -> {RESTRICTED_FIELD} (restricted)",
             use_container_width=True, disabled=busy):
    preset = "Set the account status to Space Tourism"
if c3.button("Valid existing value", use_container_width=True, disabled=busy):
    valid = schema[OPEN_FIELD]["values"][0] if OPEN_FIELD in schema else "Banking"
    preset = f"Mark this account's industry as {valid}"

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

typed = st.chat_input("Instruct the agent…", disabled=busy)
user_query = preset or typed

if user_query and not busy:
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.chat_message("assistant"):
        with st.spinner(f"[{label}] generating tool call…"):
            tok, mdl = load_model(model_id)
            t0 = time.time()
            raw = run_agent(tok, mdl, user_query, temp, build_tool_spec(schema))
            agent_ms = (time.time() - t0) * 1000

        payload = extract_json(raw)
        if payload is None or "arguments" not in payload:
            st.warning("Agent did not return a parseable tool call.")
            st.code(raw)
            st.stop()

        st.markdown("**Agent-generated tool call:**")
        st.code(json.dumps(payload, indent=2), language="json")

        log = {"prompt": user_query, "model": model_id, "payload": payload}

        # ---- FIREWALL BYPASSED ----
        if not guard_on:
            ok, err, ms = commit(sf, rec_id, payload["arguments"])
            if ok:
                out = (f"**COMMITTED - NO CHECKS PERFORMED.**\n\n"
                       f"The API accepted this write without complaint. "
                       f"Scroll up: the live org state has changed.\n\n"
                       f"*Agent: {agent_ms:.0f} ms · API: {ms:.0f} ms*")
            else:
                out = (f"**API REJECTED THE WRITE.**\n\n`{err}`\n\n"
                       f"*Agent: {agent_ms:.0f} ms · API: {ms:.0f} ms*")
            st.markdown(out)
            st.session_state.messages.append({"role": "assistant", "content": out})
            st.session_state.audit.append({**log, "guard": False,
                                           "outcome": "committed" if ok else "api_error"})
            st.rerun()

        # ---- LAYER 1 ----
        t0 = time.time()
        result = layer1_metadata(payload, schema)
        guard_ms = (time.time() - t0) * 1000
        log["detect_ms"] = round(guard_ms, 3)

        if result and result[0] == "ESCALATE":
            _, code, reason = result
            st.session_state.pending = {"payload": payload, "code": code,
                                        "reason": reason,
                                        "log": {**log, "code": code}}
            st.rerun()

        elif result:
            _, code, reason = result
            out = (f"**BLOCKED BY ACTGUARD**\n\n"
                   f"- **Interceptor:** `Layer 1 (Metadata Cache)`\n"
                   f"- **Error code:** `{code}`\n"
                   f"- **Reason:** {reason}\n"
                   f"- No API call was made.\n\n"
                   f"*Agent: {agent_ms:.0f} ms · Detection: {guard_ms:.2f} ms*")
            st.markdown(out)
            st.session_state.messages.append({"role": "assistant", "content": out})
            st.session_state.audit.append({**log, "code": code, "outcome": "blocked"})

        else:
            ok, err, ms = commit(sf, rec_id, payload["arguments"])
            out = ((f"**PASSED LAYER 1 - COMMITTED**\n\n"
                    f"All values exist in the org's value sets.\n\n"
                    f"*Agent: {agent_ms:.0f} ms · Detection: {guard_ms:.2f} ms · "
                    f"API: {ms:.0f} ms*") if ok else
                   f"**PASSED LAYER 1, BUT API REJECTED:**\n\n`{err}`")
            st.markdown(out)
            st.session_state.messages.append({"role": "assistant", "content": out})
            st.session_state.audit.append({**log,
                                           "outcome": "committed" if ok else "api_error"})
        st.rerun()

if st.session_state.audit:
    with st.expander(f"Session audit log ({len(st.session_state.audit)} actions)"):
        st.json(st.session_state.audit)
        st.download_button("Download audit JSON",
                           json.dumps(st.session_state.audit, indent=2),
                           "actguard_session_audit.json")
