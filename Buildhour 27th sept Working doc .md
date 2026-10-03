# Last Week Slides \- [RAG Slides Final](https://docs.google.com/presentation/d/199kHdwwMBRd5vh7XjDYDsGp5pRzyhlagMXZeugd7FWY/edit?usp=sharing)

# Prompt 1 ( Initial Work) 

For → [https\://groww.in/](https://groww.in/) → Pick one AMC \= HDFC and 3–5 schemes under it (e.g., one large-cap, one flexi-cap, one ELSS).

* Collect 5 public pages from AMC

Need 5 public pages to build RAG just give me 5 links for hdfc

5 Schemes

Here are the 5 Groww pages for HDFC, one per category, all Direct–Growth plans:

1. **Large Cap:** [https\://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth)  
2. **Flexi Cap:** [https\://groww.in/mutual-funds/hdfc-equity-fund-direct-growth](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth)  
3. **ELSS:** [https\://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)  
4. **Small Cap:** [https\://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth)  
5. **Balanced Advantage (Hybrid):** [https\://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth](https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth)

# Problems Statement

#### Mutual Fund FAQs (Facts-Only Q\&A)

#### Milestone brief

Build a small FAQ assistant that answers **facts about mutual fund schemes**—e.g., expense ratio, exit load, minimum SIP, lock-in (ELSS), riskometer, benchmark, and how to download statements—using **only official public pages**. Every answer must include **one source link**. No advice.

##### Who this helps

Retail users comparing schemes; support/content teams answering repetitive MF questions.

##### What you must build

##### Scope your corpus: Pick one AMC and 3–5 schemes under it (e.g., one large-cap, one flexi-cap, one ELSS).

* **Collect the public pages as mentioned below public pages** from AMC/SEBI/AMFI (factsheets, KIM/SID, scheme FAQs, fee/charges pages, riskometer/benchmark notes, statement/tax-doc guides).  
  * **Large Cap:** [https\://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth)  
  * **Flexi Cap:** [https\://groww.in/mutual-funds/hdfc-equity-fund-direct-growth](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth)  
  * **ELSS:** [https\://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)  
  * **Small Cap:** [https\://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth)  
  * **Balanced Advantage (Hybrid):** [https\://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth](https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth)  
* **FAQ assistant (working prototype):**  
  * Answers **factual queries only** (e.g., “Expense ratio of ?”, “ELSS lock-in?”, “Minimum SIP?”, “Exit load?”, “Riskometer/benchmark?”, “How to download capital-gains statement?”).  
  * Shows **one clear citation link** in every answer.  
  * **Refuses** opinionated/portfolio questions (e.g., “Should I buy/sell?”) with a polite, facts-only message and a relevant educational link.  
  * Tiny UI: welcome line \+ **3 example questions** and a note: “Facts-only. No investment advice.”

##### Key constraints

* \*\*Public sources only.\*\* No screenshots of the app back-end; no third-party blogs as sources.  
* \*\*No PII.\*\* Do not accept/store PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers.  
* \*\*No performance claims.\*\* Don’t compute/compare returns; link to the official factsheet if asked.  
* \*\*Clarity & transparency.\*\* Keep answers ≤3 sentences; add “Last updated from sources: ”.

##### What to submit (deliverables)

* **Working prototype link** (app/notebook) or a **≤3-min demo video** if hosting isn’t possible.  
* **Source list** (CSV/MD) of the 5 URLs you used.  
* **README** with setup steps, scope (AMC \+ schemes), and known limits.  
* **Sample Q\&A file** (5–10 queries with the assistant’s answers \+ links).  
* **Disclaimer snippet** used in your UI (facts-only, no advice).

End output \- RAG Chatbot 

Each stage is different and when we create architecture we wwant to follow all the stages on RAG ( Data ingestion \+ Data retrieval) 

**What we're building:** A RAG (Retrieval-Augmented Generation) chatbot that answers questions using only the provided source data.

**Pipeline**

Ingestion:  Load → Chunk → Embed → Store in Vector DB

Query:      Question → Embed → Retrieve top chunks → LLM → Answer

**Tech constraints**

* **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`. It runs locally, needs no API key, and produces 384-dimension vectors. Use the same model to embed both the chunks and the user's question.  
* **Chunking strategy:** the AI agent (Cursor, OpenCode, or Claude Code) decides. Before it writes any code, it should inspect the data and propose a strategy, say why it suits this data, and specify chunk size, overlap, and what metadata each chunk keeps. Save all chunks to a readable `.txt` file so they can be inspected.  
* **Vector DB:** ChromaDB, persisted to disk, so ingestion runs once and not on every restart.  
* **LLM:** Groq, with the API key stored in `.env` and never committed to Git.

### **Pre-Requisite** 

1. Download Cursor   
2. Click IDE on top right corner to open IDE   
3. In Cursor IDE , click open project \-\> Create New Folder \-\> Cursor will open   
4. In Cursor Create A file called Problemstatement.txt   
   1. Past problem statement form tab “Problem statement”   
   2. Follow the prompts 

**Note : You can use OpenCode/ Claude in cursor if you are not on paid subscriiption**

### **Replay** 

**Data Ingestion :**\- Loading → Chunking → Embedding —\> Vector Space   
**Data Retrieval :-** Query → embedding → find chunk in vector space → (Augmentation)LLM \+ Chunk \+ system prompt → Generate Answer 

### **Tech Decisions we took in class** 

**Embedding model:** sentence-transformers/all-MiniLM-L6-v2. It runs locally, **needs no API key,** and produces 384-dimension vectors. Use the same model to embed both the chunks and the user's question.

**Chunking strategy: t**he AI agent (Cursor, OpenCode, or Claude Code) decides. Before it writes any code, it should inspect the data and propose a strategy, say why it suits this data, and specify chunk size, overlap, and what metadata each chunk keeps. Save all chunks to a readable .txt file so they can be inspected.

**Vector DB:** ChromaDB, persisted to disk, so ingestion runs once and not on every restart.

**LLM ( for data retrieval )** : **Groq**, with the API key stored in .env and never committed to Git. Go here \- [https\://console.groq.com/keys](https://console.groq.com/keys), create a API Key. GROQ\_MODEL=qwen/qwen3.8-27b

# Prompts

1. Create PRD.md from the Problemstatement.txt , we are basically building. aRAG chatbot for a class demo  
1. create architecture.md on the basis of PRD.md   
2. create implementation.md which has phase-wise implementation details which I can use to guide cursor to implement in phases using architecture.md   
3. implement phase 1 from [implementation.md](http://implementation.md)  
4. implement phase 2 using @docs/[implementation.md](http://implementation.md) ( loading & Chunking)   
5. Implement phase 3 using [implementation.md](http://implementation.md)  embed & Storing vector DB  
6. I dont see chunks and raw data in data folder ? is chunking done.  
7. I want to see chunks and embedding. Need to see it in txt file  
8. Is data present in chromadb already, is is persistent   
9. implement phase 4 using @docs/implementation.md (Gurdails)   
10. implement phase 5 using @docs/implementation.md ( Retrieval ) \<\>   
11. I want to test the retrieval. how to test it ?   
12. create a .env for me to add LLM API Keys   
13. Go here \- [https\://console.groq.com/keys](https://console.groq.com/keys), create a API Key  
14. GROQ\_API\_KEY=  
15. GROQ\_MODEL=**qwen/qwen3.8-27b**,   
16. Tested the retrieval by asking few question   
17. \<\> refining   
18. Git created repo  
19. Implement the last stage (phase 6\)  UI as per  [implementation.md](http://implementation.md)  
20. Add a memory context window of 10 for retrieval.   
21. host it locally and push it to git \- \<git repo link\>

Host on render 

22. I'm deploying this repo to Render as a Web Service. Give me the exact values for  
    Root Directory, Build Command, and Start Command, and list the environment  
    variables I need to add. The vector DB should be rebuilt during the build.  
    

On Cursor \- ask opencode to give you details to be added to host it on render. 

1. Root Directory  
2. Build Command   
3. Start Command

Sample Value :- 

| Setting | Value |
| ----- | ----- |
| Root Directory | *(leave blank if the app is at repo root)* |
| Build Command | `pip install -r requirements.txt && python -m src.ingest.run` |
| Start Command | `python -m streamlit run src/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true` |
| Environment | `GROQ_API_KEY`, `GROQ_MODEL` |

Every future `git push` triggers an automatic redeploy.

---

### **How it works (recap)**

Question → embed (same model) → search vector DB → top chunks  
        → LLM (system prompt \+ chunks \+ question) → Answer  
---

### **Optional: custom UI with Google Stitch**

1. Design your chat screen in **Stitch** and export it as a ZIP (it lands in Downloads).  
2. Prompt:

Move the Stitch export from \~/Downloads/\<file\>.zip into this project under  
design/stitch/, unzip it, and rebuild the UI to match these designs.  
Do NOT use Streamlit for this UI — use HTML/CSS/JS served by a small Python  
backend (FastAPI) that calls the existing RAG pipeline.  
Update the Render start command accordingly, then commit and push.

3. Render redeploys automatically. Open your Render URL once the build finishes.  
1. 

   

## **Build a RAG Chatbot with an AI Coding Agent**

**Works with:** Cursor or OpenCode. Prompts use `@file` references, which both tools support.

### **Before class: setup**

1. Install **Cursor** and **Python 3.10+**.  
2. Create an empty project folder, e.g. `rag-chatbot`, and open it in your tool.  
3. Create a free Groq account at [https\://console.groq.com/keys](https://console.groq.com/keys) and generate an API key. Keep it private.  
4. Create a GitHub account if you don't have one.  
5. In the project folder, create `ProblemStatement.txt` and paste in the text from the **"Problem Statement"** tab.

### **Replay** 

**Data Ingestion :**\- Loading → Chunking → Embedding —\> Vector Space   
**Data Retrieval :-** Query → embedding → find chunk in vector space → (Augmentation)LLM \+ Chunk \+ system prompt → Generate Answer 

### **Tech Decisions we took in class** 

**Embedding model:** sentence-transformers/all-MiniLM-L6-v2. It runs locally, **needs no API key,** and produces 384-dimension vectors. Use the same model to embed both the chunks and the user's question.

**Chunking strategy: t**he AI agent (Cursor, OpenCode, or Claude Code) decides. Before it writes any code, it should inspect the data and propose a strategy, say why it suits this data, and specify chunk size, overlap, and what metadata each chunk keeps. Save all chunks to a readable .txt file so they can be inspected.

**Vector DB:** ChromaDB, persisted to disk, so ingestion runs once and not on every restart.

**LLM ( for data retrieval )** : **Groq**, with the API key stored in .env and never committed to Git.

---

### **Part 1: Plan before you code**

**Prompt 1: PRD**

Read @ProblemStatement.txt. We're building a RAG chatbot for a class demo.  
Create docs/PRD.md with: goal, target users, in-scope and out-of-scope features,  
example user questions, success criteria, and constraints (free-tier tools only,  
runs locally, deployable to Render).

**Prompt 2: Architecture**

Using @docs/PRD.md, create docs/architecture.md covering: components, data flow  
(ingest → chunk → embed → store → retrieve → generate), tech stack (Python,  
ChromaDB, Groq LLM, a local embedding model), folder structure, and a simple  
text diagram of the query flow.

**Prompt 3: Implementation plan**

Using @docs/architecture.md, create docs/implementation.md with 6 phases:  
1\. Project setup  2\. Loading & chunking  3\. Embedding & vector store  
4\. Guardrails  5\. Retrieval \+ LLM answer  6\. UI  
For each phase list: files to create, what the phase does, and how I can  
verify it works before moving on. Don't write any code yet.

> 💡 Read all three docs before continuing. If something looks wrong, fix it now. It's much cheaper than fixing code later.

---

### **Part 2: Build in phases**

**Prompt 4: Phase 1 (setup)**

Implement Phase 1 from @docs/implementation.md. Create requirements.txt,  
the folder structure, and a .gitignore that excludes .env, venv, and \_\_pycache\_\_.

**Prompt 5: Phase 2 (loading & chunking)**

Implement Phase 2 from @docs/implementation.md (loading & chunking).  
Save the raw source text to data/raw/ and every chunk to data/chunks/chunks.txt  
(numbered, with source and character count), so I can inspect them.  
Then run it and tell me how many chunks were created.

**Prompt 6: Phase 3 (embedding & vector DB)**

Implement Phase 3 from @docs/implementation.md (embed chunks and store in ChromaDB).  
Use a persistent ChromaDB directory. Also write a preview of the first 5 embeddings  
(first 10 dimensions each) to data/embeddings\_preview.txt.  
Run it, then confirm the number of vectors stored and that the data persists  
after a restart.

**Prompt 7: Phase 4 (guardrails)**

Implement Phase 4 from @docs/implementation.md (guardrails): refuse off-topic  
questions, don't give advice outside the source content, and say "I don't know"  
when retrieved context doesn't answer the question.

**Prompt 8: API key setup**

Create a .env.example with GROQ\_API\_KEY= and GROQ\_MODEL=, load them with  
python-dotenv, and confirm .env is in .gitignore.

Then copy `.env.example` to `.env` and paste in your key. **Never paste your API key into the chat.**

> For `GROQ_MODEL`, pick a current model from [https\://console.groq.com/docs/models](https://console.groq.com/docs/models). Model names change often.

**Prompt 9: Phase 5 (retrieval \+ answer)**

Implement Phase 5 from @docs/implementation.md: embed the user's question with  
the SAME embedding model used in Phase 3, retrieve the top-k chunks from ChromaDB,  
and send system prompt \+ chunks \+ question to the Groq LLM.  
Add a CLI script so I can test by typing questions, and show which chunks  
were retrieved for each answer.

**Prompt 10: Test and refine**

Ask 5–6 questions: some answerable, some off-topic, some tricky. Then:

For the question "\<your question\>", the answer was \<what went wrong\>.  
Suggest and apply fixes (chunk size, overlap, top-k, or system prompt),  
then re-run the same question so I can compare.

**Prompt 11: Conversation memory**

Add conversation memory: keep the last 10 messages and use them to rewrite  
follow-up questions before retrieval (e.g. "what about its fees?" should  
resolve "its" from earlier context).

**Prompt 12: Phase 6 (UI)**

Implement Phase 6 from @docs/implementation.md: a Streamlit chat UI with message  
history, a "sources" expander under each answer, and a clear-chat button.  
Tell me the command to run it locally.  
---

### **Part 3: Ship it**

**Prompt 13: Push to GitHub**

First create an empty repo on GitHub, then:

Initialise git, make sure .env and the ChromaDB folder are NOT committed,  
commit everything, and push to \<your-repo-url\>.

**Prompt 14: Deploy on Render**

I'm deploying this repo to Render as a Web Service. Give me the exact values for  
Root Directory, Build Command, and Start Command, and list the environment  
variables I need to add. The vector DB should be rebuilt during the build.

*Sample Values:-* 

| Setting | Value |
| ----- | ----- |
| Root Directory | *(leave blank if the app is at repo root)* |
| Build Command | `pip install -r requirements.txt && python -m src.ingest.run` |
| Start Command | `python -m streamlit run src/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true` |
| Environment | `GROQ_API_KEY`, `GROQ_MODEL` |

Every future `git push` triggers an automatic redeploy.

---

### **How it works (recap)**

Question → embed (same model) → search vector DB → top chunks  
        → LLM (system prompt \+ chunks \+ question) → Answer  
---

### **Optional: custom UI with Google Stitch**

1. Design your chat screen in **Stitch** and export it as a ZIP (it lands in Downloads).  
2. Prompt:

Move the Stitch export from \~/Downloads/\<file\>.zip into this project under  
design/stitch/, unzip it, and rebuild the UI to match these designs.  
Do NOT use Streamlit for this UI — use HTML/CSS/JS served by a small Python  
backend (FastAPI) that calls the existing RAG pipeline.  
Update the Render start command accordingly, then commit and push.

3. Render redeploys automatically. Open your Render URL once the build finishes.

## **Using OpenCode inside Cursor**

OpenCode runs in Cursor's built-in terminal. When you launch it there the first time, it installs its Cursor extension automatically. It works with VS Code, Cursor, or any IDE that has a terminal. 

### **1\. Install OpenCode (one time)**

Open a terminal (Mac/Linux) and run:

curl \-fsSL https\://opencode.ai/install | bash

Other install options:

* **Any OS with Node.js:** `npm install -g opencode-ai`

Check that it installed: `opencode --version`

### **2\. Open your project in Cursor**

1. Open Cursor → **Open Project** → select (or create) your project folder, e.g. `rag-chatbot`.  
2. Open the terminal inside Cursor: **Terminal → New Terminal** (or \<kbd\>Ctrl\</kbd\>+\<kbd\>\`\</kbd\>).

### **3\. Launch OpenCode**

In Cursor's terminal, type:

opencode

The first time you run it in Cursor's terminal, the extension installs on its own. If it doesn't, search for "OpenCode" in the Extensions marketplace and click Install. 

**Useful shortcuts once the extension is installed:**

* `Cmd+Esc` (Mac) or `Ctrl+Esc` (Windows/Linux) opens OpenCode in a split terminal view   
* `Cmd+Option+K` (Mac) or `Alt+Ctrl+K` (Windows/Linux) inserts a file reference into your prompt 

### **4\. Connect an LLM provider (one time)**

Inside OpenCode, type:

/connect

Pick a provider from the list and paste its API key. You can use:

* **Groq**, with the same key from console.groq.com that the chatbot uses, or  
* **OpenCode Zen**, a curated set of models the OpenCode team has tested, which it recommends for beginners. It needs a sign-in and billing details at opencode.ai/auth. 

Then type `/models` to choose which model to use.

### **5\. Initialise the project**

/init

This analyses your project and creates an `AGENTS.md` file in the project root, which you should commit to Git. 

### **6\. Start prompting**

Now paste the prompts from the RAG handout in order.

* **Reference files** by typing `@`, e.g. `@docs/implementation.md`. It fuzzy-searches your project's files.   
* **Plan before building:** press Tab to switch to Plan mode, where OpenCode suggests how it will build something without changing any files. Press Tab again to go back to Build mode.   
* **Undo a bad change:** type `/undo` to revert the last change. You can run it several times, and `/redo` restores a change. 

### **Troubleshooting**

* **Extension didn't install:** make sure the `cursor` command is available in your terminal. If it isn't, open the Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`) and run "Shell Command: Install 'cursor' command in PATH".   
* **`opencode: command not found`:** close and reopen Cursor's terminal (or restart Cursor) so it picks up the new install.  
* **Cursor's own AI vs OpenCode:** students using OpenCode should type prompts in the terminal panel, not in Cursor's chat sidebar.

Sources:

* [OpenCode Intro](https://opencode.ai/docs/)  
* [OpenCode IDE](https://opencode.ai/docs/ide/)

## **Claude Code CLI inside Cursor**

**Account needed:** Pro, Max, Team, Enterprise, or Console. The free claude.ai plan doesn't include Claude Code.

### **Setup**

1. **Install once** (in any terminal):  
   * **Mac, Linux, or WSL:** `curl -fsSL https://claude.ai/install.sh | bash`  
   * **Windows PowerShell:** `irm https://claude.ai/install.ps1 | iex`  
   * **Homebrew:** `brew install --cask claude-code`  
2. **Verify:** open a new terminal and run `claude --version`.  
3. **Open your project in Cursor**, then go to **Terminal → New Terminal** (or \<kbd\>Ctrl\</kbd\>+\<kbd\>\`\</kbd\>).  
4. **Start Claude:** type `claude`. The first run opens a browser window to log in.  
5. **Initialise the project:** run `/init`. This creates `CLAUDE.md`, a notes file Claude reads at the start of every session.

### **Slash commands**

| Command | What it does |
| ----- | ----- |
| `/init` | Creates `CLAUDE.md` for the project. Run this first. |
| `/plan <task>` | Plans the task and waits for your approval before editing |
| `/clear` | Starts a fresh conversation. Use it between phases. |
| `/compact` | Summarises a long chat to free up context |
| `/model` | Switches the model |
| `/rewind` | Goes back to an earlier point in the chat and in your code |
| `/resume` | Reopens a past conversation |
| `/usage` | Shows plan limits and how much you've used |
| `/status` | Shows version, account, and model |
| `/permissions` | Sets which commands Claude can run without asking |
| `/ide` | Connects Claude to Cursor, for diffs and file context |
| `/help` | Lists all commands |
| `/logout` | Signs out |

### **Keyboard tips**

* `@filename` references a file, e.g. `@docs/implementation.md`.  
* `!` followed by a command runs it directly, e.g. `!pip install -r requirements.txt`.  
* `Shift+Tab` cycles permission modes (normal → auto-accept edits → plan).  
* `Esc` stops Claude mid-task.  
* `Esc Esc` rewinds to an earlier message.  
* `Shift+Enter` adds a new line without sending.

### **Terminal commands (outside Claude)**

| Command | What it does |
| ----- | ----- |
| `claude` | Starts a session in the current folder |
| `claude --resume` | Picks a past conversation to continue |
| `claude doctor` | Checks your install for problems |
| `claude update` | Updates to the latest version |

### **RAG class workflow**

1. Run `/init` once.  
2. Press `Shift+Tab` until you're in plan mode, then paste the "Implement Phase N" prompt.  
3. Review the plan and approve it.  
4. Test the phase, then run `!git add . && git commit -m "phase N"`.  
5. Run `/clear` and move to the next phase.

Sources:

* [Claude Code setup](https://code.claude.com/docs/en/setup)  
* [Claude Code in VS Code/Cursor](https://code.claude.com/docs/en/ide-integrations)

### **Install OpenCode without npm**

**Mac / Linux**

curl \-fsSL https\://opencode.ai/install | bash

Or with Homebrew: `brew install anomalyco/tap/opencode`

**Windows (pick one)**

choco install opencode  
scoop install opencode

Or download the binary from the [GitHub Releases page](https://github.com/anomalyco/opencode/releases) and add it to your PATH.

Then open a new terminal and check that it installed: `opencode --version`

---

### **If you still want npm**

npm comes bundled with Node.js, so installing Node gives you npm too.

* **Any OS:** download the **LTS** installer from [https\://nodejs.org](https://nodejs.org) and run it.  
* **Mac:** `brew install node`  
* **Windows:** `winget install OpenJS.NodeJS.LTS`  
* **Ubuntu/WSL:** `sudo apt update && sudo apt install nodejs npm`

Then close and reopen your terminal and check:

node \-v  
npm \-v

Now `npm install -g opencode-ai` will work.

---

### **Alternatives when a laptop won't cooperate**

**1\. WSL on Windows**

OpenCode recommends WSL for the best experience on Windows. It gives you a Linux terminal inside Windows.

1. Open PowerShell as Administrator and run `wsl --install`.  
2. Restart your computer and set a Linux username and password.  
3. Open **Ubuntu** from the Start menu and run the curl install command above.  
4. In Cursor, install the **WSL** extension, then use **"Connect to WSL"** so the terminal and your files live in Linux.

**2\. Docker (no install on the machine itself)**

If Docker Desktop is installed, run OpenCode inside a container. The `-v` and `-w` flags mount your current project folder so OpenCode can see your files:

docker run \-it \--rm \-v "\$PWD":/app \-w /app ghcr.io/anomalyco/opencode

On Windows PowerShell, replace `$PWD` with `${PWD}`.

**3\. GitHub Codespaces (cloud VM, just a browser)**

This is the best fallback for locked-down or low-spec laptops.

1. Push the project to GitHub.  
2. On the repo page, click **Code → Codespaces → Create codespace**. A VS Code editor opens in the browser, running on a Linux VM.  
3. In its terminal, run `curl -fsSL https://opencode.ai/install | bash`, then `opencode`.

Personal GitHub accounts include a free monthly Codespaces quota. Tell students to stop their codespace after class so they don't use it up.

---

### **Suggested fallback order for class**

1. The curl script, or choco/scoop on Windows  
2. WSL, for Windows students where option 1 fails  
3. Codespaces, if anything else breaks. It's the quickest way to unblock someone during a live session.

Sources:

* [OpenCode install docs](https://opencode.ai/docs/)  
* [OpenCode on Windows / WSL](https://opencode.ai/docs/windows-wsl)

