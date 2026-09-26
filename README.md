# AI Code Review & PR Assistant

An automated security auditing and pull request review engine built with FastAPI, AST-based code analysis, and IBM Bob IDE.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [IBM Bob 2.0 Integration](#ibm-bob-20-integration)
- [License](#license)

---

## Overview

The **AI Code Review & PR Assistant** is a developer-focused tool designed to streamline pull request auditing and code reviews. By combining static Abstract Syntax Tree (AST) analysis with rule-based heuristics, it automatically inspects Git diffs for potential security vulnerabilities, bad practices, and anti-patterns, generating clear and actionable Markdown reports for GitHub pull requests.

Key goals:
- **Accelerate PR turnaround** by catching common anti-patterns before human reviewers step in.
- **Surface security risks** like hardcoded secrets, dangerous evaluations, and SQL injection vectors.
- **Provide zero-friction setup** with a fast, lightweight Python and FastAPI engine.

---

## Features

- 🔍 **AST-Based Static Analysis** — Inspects Python code using the standard AST library to spot syntax and structural issues without executing untrusted code.
- ⚡ **Git Diff Parsing** — Automatically extracts added/modified lines from Git diffs to target the review precisely on incoming changes.
- 🛡️ **Security Rule Auditing** — Detects hardcoded API keys/passwords, unsafe calls (`eval`, `exec`), and insecure SQL queries.
- 📋 **One-Click Markdown Export** — Produces ready-to-post pull request review comments with severity badges and actionable suggestions.
- 📊 **Developer Dashboard** — Simple and responsive web UI for pasting diffs and viewing instant review breakdowns.

---

## Project Structure

```text
ai-code-review-assistant/
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py             # FastAPI review endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   └── reviewer.py           # AST engine & Git diff inspection logic
│   ├── static/
│   │   └── index.html            # Interactive web dashboard
│   ├── __init__.py
│   └── main.py                   # FastAPI application entrypoint
├── bob-session-proof.png         # IBM Bob IDE session verification
├── .env.example                  # Example environment config
├── .gitignore                    # Ignored files
├── requirements.txt              # Python project dependencies
└── README.md                     # Project documentation