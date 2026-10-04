import os

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(page_title="TokenOS", layout="wide")
st.title("TokenOS · Adaptive Agent Runtime")
st.caption("Inspect context allocation, task outcomes, tool evidence, and budget accounting.")
base = st.sidebar.text_input("API URL", os.getenv("TOKENOS_API_URL", "http://127.0.0.1:8000"))
key = st.sidebar.text_input("API key", os.getenv("TOKENOS_API_KEY", ""), type="password")


def api(method, path, body=None):
    with httpx.Client(timeout=300) as client:
        response = client.request(method, base + path, headers={"X-API-Key": key}, json=body)
        response.raise_for_status()
        return response.json()


try:
    info = api("GET", "/v1/runtime")
except Exception:
    st.info("Start the API and enter its API key to connect.")
    st.stop()
st.sidebar.json(info)
if info["source"] == "simulated":
    st.warning("Sandbox: deterministic fixtures; byte counts are not measured LLM efficiency.")
else:
    st.info("Live provider: tasks send context externally and may incur charges.")
run, inspect, knowledge, evaluation = st.tabs(
    ["Run task", "Inspect", "Knowledge & tools", "Evaluation"]
)
with run:
    with st.form("run"):
        query = st.text_area("Task", "Create a return for order ORD100 using the return policy.")
        mode = st.selectbox("Allocation policy", ["adaptive", "fixed", "full"])
        budget = st.number_input("Task token budget", min_value=1, value=60000)
        history = st.text_area("History (one item per line)")
        submitted = st.form_submit_button("Run task")
    if submitted:
        try:
            result = api(
                "POST",
                "/v1/tasks",
                {
                    "query": query,
                    "mode": mode,
                    "budget_tokens": budget,
                    "history": history.splitlines(),
                },
            )
            st.session_state["last_task"] = result["request"]["task_id"]
            st.write(result["status"])
            st.write(result.get("answer"))
            st.json(result)
        except Exception as error:
            st.error(type(error).__name__)
with inspect:
    task_id = st.text_input("Task ID", st.session_state.get("last_task", ""))
    if task_id:
        try:
            data = api("GET", f"/v1/tasks/{task_id}")
            st.json(data["ledger"])
            decisions = data["task"]["decisions"]
            if decisions:
                st.bar_chart(pd.DataFrame([d["retained"] for d in decisions]))
            st.json(data["task"])
        except Exception as error:
            st.error(type(error).__name__)
with knowledge:
    with st.form("document"):
        doc_id = st.text_input("Document ID")
        title = st.text_input("Title")
        content = st.text_area("Document text")
        save = st.form_submit_button("Index document")
    if save:
        try:
            st.json(
                api(
                    "POST",
                    "/v1/documents",
                    {"document_id": doc_id, "title": title, "text": content},
                )
            )
        except Exception as error:
            st.error(type(error).__name__)
    if st.button("List documents and tools"):
        st.json(api("GET", "/v1/documents"))
        st.json(api("GET", "/v1/tools"))
    server = st.text_input("Configured MCP server name")
    if st.button("Discover MCP tools"):
        try:
            st.json(api("POST", f"/v1/mcp/{server}/discover"))
        except Exception as error:
            st.error(type(error).__name__)
with evaluation:
    st.write("Run scripts/benchmark.py, then upload the resulting report.")
    report = st.file_uploader("Benchmark JSON", type=["json"])
    if report:
        import json

        result = json.load(report)
        st.dataframe(result["summary"])
        st.dataframe(result["rows"])
