# ActGuard: Pre-Commit Detection Framework for Action-Space Hallucinations

**Author:** Shaan Anshu (BITS ID: 2024AB05201)
**Degree:** M.Tech. in Artificial Intelligence and Machine Learning, BITS Pilani
**Organization:** Salesforce India, Hyderabad

---

## 📌 Overview
This repository contains the official implementation of **ActGuard**, a multi-layered pre-commit detection framework designed to mitigate action-space hallucinations in tool-using Large Language Model (LLM) agents. 

While current AI research heavily focuses on textual hallucinations and tool-selection errors, a critical gap exists in the action-execution stage. ActGuard intercepts syntactically valid but domain-invalid actions before they commit to enterprise platforms, preventing silent state corruption.

## 📂 Repository Structure
* **`ActGuard_VIVA_Presentation_V_Final.ipynb`**: The primary execution notebook. Contains the CRM-ActHallu benchmark generation, metadata caching, and the multi-model evaluation loop.
* **`app.py`**: A complete Streamlit dashboard for live, interactive agentic guardrail demonstrations. 
* **`actguard_results.csv`**: The empirical evaluation results across 156 scenarios spanning five standard Salesforce objects (Account, Opportunity, Case, Lead, and Contact).
* **`viva_audit_log.txt`**: The verifiable audit artifact containing raw API interaction traces proving the execution of all benchmark checks.

## 🛡️ Framework Architecture
ActGuard enforces constraints via a risk-tiered architecture:
1. **Layer 1 (Metadata Cache):** Performs deterministic validation against cached org metadata to intercept schema divergence (e.g., unrestricted picklist violations) in microseconds.
2. **Layer 3 (Sandbox API Execution):** Executes actions against a live org sandbox to detect runtime state violations and business logic constraints (e.g., locked records, validation rules).

## 📊 Key Findings
Evaluated on Qwen, Llama-3, and Mistral architectures, ActGuard achieved:
* **100.0% Precision:** Zero false positives.
* **0.0% False Abstention Rate:** Imposes zero operational cost on legitimate enterprise workflows.
* **Configuration Dependency:** Demonstrated that identical agent errors result in silent data corruption or hard rejection strictly based on underlying org configuration.

## 📜 License
The code in this repository is released under the MIT License. The CRM-ActHallu dataset is released under CC-BY-4.0.
