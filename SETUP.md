# 🛠️ ActGuard Setup & Execution Guide

This guide provides step-by-step instructions on how to configure, install, and run the ActGuard framework and its interactive Streamlit dashboard. 

Because ActGuard relies on local LLM inference and live Salesforce API interactions, we highly recommend running this framework in **Google Colab** (with a T4 GPU) or a local machine with a dedicated CUDA-enabled GPU.

---

## 1. Prerequisites

Before running the code, you will need:
1. **Salesforce Developer Edition Org:** A free testing environment. You can sign up for one at [developer.salesforce.com](https://developer.salesforce.com/).
2. **Salesforce Connected App:** You must create a Connected App in your Salesforce Org with OAuth2 enabled (Client Credentials flow) to get a `CLIENT_ID` and `CLIENT_SECRET`.
3. **Hardware:** A GPU with at least 16GB of VRAM (Google Colab's free T4 GPU is perfectly sufficient for the 1.5B to 8B parameter models used in this research).

---

## 2. Salesforce Environment Configuration

ActGuard validates against live Salesforce metadata. To replicate the benchmark perfectly, ensure your Salesforce org has the following configurations:
*   **Target Objects:** Account, Opportunity, Case, Lead, Contact.
*   **Restricted Picklist Test (Class 1a):** Create a custom picklist field on the `Account` object named `Status__c`. Ensure the **"Restrict picklist to the values defined in the value set"** checkbox is **ENABLED**.
*   **Record Lock Test (Class 2):** Create an active Approval Process on the `Opportunity` object and ensure the **"Record Lock"** action is configured upon submission.

---

## 3. Installation

Clone the repository and install the required Python dependencies.

```bash
# Clone the repository
git clone [https://github.com/YourGitHubUsername/ActGuard-Framework.git](https://github.com/YourGitHubUsername/ActGuard-Framework.git)
cd ActGuard-Framework

# Install required packages
pip install simple-salesforce requests transformers accelerate torch streamlit pandas
```

---

## 4. Injecting Credentials

For security reasons, enterprise credentials are not hardcoded in this repository. Before running the framework, you must inject your Salesforce OAuth2 credentials.

1. Open `app.py` and `actguard_core.py` (or the Jupyter Notebook).
2. Locate the authentication block near the top of the files.
3. Replace the placeholder strings with your actual credentials:

```python
CLIENT_ID = "YOUR_SALESFORCE_CLIENT_ID"
CLIENT_SECRET = "YOUR_SALESFORCE_CLIENT_SECRET"
LOGIN_URL = "[https://your-domain.my.salesforce.com/services/oauth2/token](https://your-domain.my.salesforce.com/services/oauth2/token)"
INSTANCE_URL = "[https://your-domain.my.salesforce.com](https://your-domain.my.salesforce.com)"
```

---

## 5. Running the Empirical Benchmark

To execute the benchmark generation, LLM payload generation, and pre-commit detection loop, run the core backend script:

```bash
python actguard_core.py
```
*(Alternatively, execute the cells sequentially in `ActGuard_VIVA_Presentation_V_Final.ipynb`)*. 

This will automatically query your org's metadata, run the agent scenarios, intercept violations, and generate the `actguard_results.csv` and `viva_audit_log.txt` artifacts.

---

## 6. Launching the Interactive Dashboard

ActGuard includes a live, interactive Streamlit dashboard to demonstrate pre-commit interception in real-time.

### Running Locally
If you are running this on a local machine, simply execute:
```bash
streamlit run app.py
```
The dashboard will open automatically in your browser at `http://localhost:8501`.

### Running in Google Colab
Since Colab does not have a native display for local web servers, use Cloudflared (or Localtunnel) to expose the dashboard to the public web. Run the following in a Colab cell:

```bash
# Start Streamlit in the background
streamlit run app.py --server.headless=true &

# Download and run Cloudflared to create a secure tunnel
wget -q -nc [https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64](https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64)
chmod +x cloudflared-linux-amd64
./cloudflared-linux-amd64 tunnel --url http://localhost:8501
```
Click the generated `*.trycloudflare.com` link in the output to access your live ActGuard control panel!
