"""
backend.py — Codefolio backend engine
- Each repo gets a single Markdown summary file.
- Uses OpenAI if available; otherwise falls back to a heuristic summary.
"""

import os
import re
from pathlib import Path
from collections import Counter

try:
    from github import Github
except Exception:
    raise RuntimeError("PyGithub required: pip install PyGithub")

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ---------------- utils ----------------
TEXT_EXTENSIONS = {".py",".js",".ts",".jsx",".tsx",".java",".c",".cpp",".md",".txt",".html",".css",".json",".yml",".yaml",".rs",".go",".sh"}
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w\.\-]+)", re.MULTILINE)

# Directories to skip during scanning
IGNORED_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", ".eggs", "*.egg-info",
    ".pytest_cache", ".tox", ".nox",
    "vendor", "vendors", "third_party",
    ".idea", ".vscode", ".vs"
}

# Virtual environment patterns (more aggressive)
VENV_PATTERNS = [
    "venv", "env", "myenv", "myvenv", ".venv", "virtualenv",
    "site-packages", "/lib/", "/scripts/", "/include/",
    "/share/", "/bin/", "pyvenv"
]

def should_skip_path(path):
    """Check if a path should be skipped based on ignored directories."""
    import urllib.parse
    # Decode URL-encoded paths
    path_decoded = urllib.parse.unquote(path).lower()
    
    # Split path into parts
    path_parts = path_decoded.replace("\\", "/").split("/")
    
    for part in path_parts:
        # Skip hidden directories
        if part.startswith(".") and part not in [".", ".."]:
            return True
        
        # Skip exact matches
        if part in IGNORED_DIRS:
            return True
            
        # Skip virtual environment patterns
        for pattern in VENV_PATTERNS:
            if pattern in part:
                return True
    
    # Additional checks for common venv indicators
    if any(indicator in path_decoded for indicator in ["site-packages", "/lib/", "/scripts/", "/share/", "/pyvenv"]):
        return True
        
    return False

def is_text_file(name):
    return any(name.lower().endswith(ext) for ext in TEXT_EXTENSIONS)

def send_progress(cb, stage, pct=0, message=""):
    if cb:
        try:
            cb((stage, int(pct), message))
        except Exception:
            pass

# ---------------- walk repo ----------------
def walk_repo_files(repo, path="", stats=None):
    """Walk through repository files, skipping ignored directories.
    
    Args:
        repo: GitHub repository object
        path: Current path being walked
        stats: Optional dict to track statistics (skipped_dirs, skipped_files)
    """
    if stats is None:
        stats = {"skipped_dirs": 0, "skipped_files": 0}
    
    try:
        contents = repo.get_contents(path)
    except Exception:
        return
    for item in contents:
        if item.type == "dir":
            # Skip ignored directories
            if should_skip_path(item.path):
                stats["skipped_dirs"] += 1
                continue
            yield from walk_repo_files(repo, item.path, stats)
        elif item.type == "file":
            # Skip files in ignored paths
            if should_skip_path(item.path):
                stats["skipped_files"] += 1
                continue
            if not is_text_file(item.name):
                continue
            try:
                raw = item.decoded_content
                try:
                    text = raw.decode("utf-8")
                except Exception:
                    text = raw.decode("latin-1", errors="ignore")
                yield {"path": item.path, "content": text, "sha": item.sha}
            except Exception:
                continue

# ---------------- feature detection ----------------
def analyze_code_functionality(samples):
    """Deeply analyze code to understand what it actually does."""
    functionality = {
        "endpoints": [],
        "functions": [],
        "classes": [],
        "business_logic": [],
        "comments": [],
        "docstrings": [],
        "user_flows": []
    }
    
    for sample in samples:
        code = sample.get("snippet", "")
        path = sample.get("path", "")
        
        # Extract API endpoints - be more specific
        route_patterns = [
            (r'@app\.route\(["\']([^"\']+)["\']', 'Flask', 1),
            (r'@app\.(get|post|put|delete)\(["\']([^"\']+)["\']', 'FastAPI', 2),
            (r'@router\.(get|post|put|delete)\(["\']([^"\']+)["\']', 'FastAPI', 2),
            (r'path\(["\']([^"\']+)["\']', 'Django', 1),
        ]
        
        for pattern, framework, path_group in route_patterns:
            matches = re.finditer(pattern, code)
            for match in matches:
                endpoint_path = match.group(path_group)
                # Only add if it looks like a real path (starts with /)
                if endpoint_path and endpoint_path.startswith('/'):
                    functionality["endpoints"].append({
                        "path": endpoint_path,
                        "framework": framework,
                        "file": path
                    })
        
        # Extract function names and purposes
        func_pattern = r'def\s+(\w+)\s*\([^)]*\):'
        func_matches = re.finditer(func_pattern, code)
        for match in func_matches:
            func_name = match.group(1)
            if not func_name.startswith('_'):  # Skip private functions
                # Try to get docstring
                after_def = code[match.end():match.end()+300]
                doc_match = re.search(r'"""([^"]+)"""', after_def)
                description = doc_match.group(1).strip() if doc_match else func_name.replace('_', ' ')
                
                # Store docstrings separately for context
                if doc_match:
                    functionality["docstrings"].append(doc_match.group(1).strip())
                
                functionality["functions"].append({
                    "name": func_name,
                    "description": description,
                    "file": path
                })
        
        # Extract meaningful comments
        comment_pattern = r'#\s*(.+)$'
        comment_matches = re.finditer(comment_pattern, code, re.MULTILINE)
        for match in comment_matches:
            comment_text = match.group(1).strip()
            # Filter out short or code-like comments
            if len(comment_text) > 20 and not comment_text.startswith('-'):
                functionality["comments"].append(comment_text)
        
        # Extract class names
        class_pattern = r'class\s+(\w+)(?:\([^)]*\))?:'
        class_matches = re.finditer(class_pattern, code)
        for match in class_matches:
            class_name = match.group(1)
            functionality["classes"].append({
                "name": class_name,
                "file": path
            })
        
    # Detect business logic patterns - deduplicate as we go
    business_logic_set = set()
    user_flows_set = set()
    
    # Combine all code for pattern detection
    all_code = "\n".join([s.get("snippet", "") for s in samples]).lower()
    
    # Only detect if pattern appears in function context (not just comments)
    if ("def send_email" in all_code or "mail.send" in all_code or "smtp" in all_code):
        business_logic_set.add("Email sending capability")
    
    if ("stripe" in all_code or "payment_intent" in all_code) and "def" in all_code:
        business_logic_set.add("Payment processing")
        user_flows_set.add("Users can make purchases and payments")
    
    if "webhook" in all_code and ("def" in all_code or "@app" in all_code):
        business_logic_set.add("Webhook handling")
    
    if ("upload" in all_code and "file" in all_code) and ("def upload" in all_code or "upload_file" in all_code):
        business_logic_set.add("File upload functionality")
        user_flows_set.add("Users can upload files or images")
    
    if "@celery" in all_code or "celery.task" in all_code:
        business_logic_set.add("Background task scheduling")
    
    if ("def login" in all_code or "def authenticate" in all_code or "@login_required" in all_code):
        business_logic_set.add("User authentication")
        user_flows_set.add("Users can log in to access their account")
    
    if ("def register" in all_code or "def signup" in all_code or "create_user" in all_code):
        business_logic_set.add("User registration")
        user_flows_set.add("New users can create an account")
    
    if ("def dashboard" in all_code or "/dashboard" in all_code or "route.*dashboard" in all_code):
        user_flows_set.add("Users can view a personalized dashboard")
    
    if ("update_profile" in all_code or "edit_profile" in all_code) and "def" in all_code:
        user_flows_set.add("Users can edit their profile information")
    
    if ("def search" in all_code or "/search" in all_code) and "query" in all_code:
        user_flows_set.add("Users can search through content")
    
    if ("def.*comment" in all_code or "create_comment" in all_code or "add_feedback" in all_code):
        user_flows_set.add("Users can leave comments or feedback")
    
    if ("send_notification" in all_code or "notify_user" in all_code):
        user_flows_set.add("Users receive notifications")
    
    if ("def export" in all_code or "download" in all_code) and ("csv" in all_code or "pdf" in all_code):
        user_flows_set.add("Users can export data")
    
    functionality["business_logic"] = list(business_logic_set)
    functionality["user_flows"] = list(user_flows_set)
    
    # Deduplicate and limit other collections
    functionality["endpoints"] = functionality["endpoints"][:15]  # Max 15 endpoints
    functionality["docstrings"] = list(set(functionality["docstrings"]))[:5]  # Max 5 docstrings
    functionality["comments"] = list(set(functionality["comments"]))[:5]  # Max 5 comments
    
    return functionality

def extract_features_from_code(samples, imports):
    """Detect features and patterns from code samples."""
    features = {
        "app_type": [],
        "deployment": [],
        "database": [],
        "apis": [],
        "frameworks": [],
        "auth": [],
        "notable_features": [],
        "functionality": {}
    }
    
    # Get deep code analysis
    features["functionality"] = analyze_code_functionality(samples)
    
    all_code = "\n".join([s.get("snippet", "") for s in samples])
    all_code_lower = all_code.lower()
    
    # Detect app type
    if "flask" in imports or "@app.route" in all_code or "@blueprint" in all_code:
        features["app_type"].append("Flask Web Application")
        features["frameworks"].append("Flask")
    if "fastapi" in imports or "@app.get" in all_code or "@app.post" in all_code:
        features["app_type"].append("FastAPI REST API")
        features["frameworks"].append("FastAPI")
    if "django" in imports:
        features["app_type"].append("Django Web Application")
        features["frameworks"].append("Django")
    if "streamlit" in imports or "st.title" in all_code:
        features["app_type"].append("Streamlit Dashboard")
        features["frameworks"].append("Streamlit")
    if "kivy" in imports:
        features["app_type"].append("Kivy Desktop Application")
        features["frameworks"].append("Kivy")
    if "react" in all_code_lower or "usestate" in all_code_lower:
        features["app_type"].append("React Web Application")
        features["frameworks"].append("React")
    
    # Detect deployment
    if "render" in all_code_lower or "render.yaml" in all_code_lower:
        features["deployment"].append("Render")
    if "heroku" in all_code_lower or "procfile" in all_code_lower:
        features["deployment"].append("Heroku")
    if "vercel" in all_code_lower:
        features["deployment"].append("Vercel")
    if "docker" in imports or "dockerfile" in all_code_lower:
        features["deployment"].append("Docker")
    if "kubernetes" in all_code_lower or "k8s" in all_code_lower:
        features["deployment"].append("Kubernetes")
    
    # Detect database
    if "sqlalchemy" in imports or "db.model" in all_code_lower:
        features["database"].append("SQL Database (SQLAlchemy)")
    if "pymongo" in imports or "mongodb" in all_code_lower:
        features["database"].append("MongoDB")
    if "psycopg2" in imports or "postgresql" in all_code_lower:
        features["database"].append("PostgreSQL")
    if "sqlite" in imports or "sqlite3" in imports:
        features["database"].append("SQLite")
    
    # Detect APIs and integrations - be specific
    if "openai" in imports or "import openai" in all_code_lower:
        features["apis"].append("OpenAI API")
    if "stripe" in imports or "import stripe" in all_code_lower:
        features["apis"].append("Stripe Payments")
    if "twilio" in imports:
        features["apis"].append("Twilio SMS/Voice")
    # Only flag External API if actually making HTTP requests to external APIs
    if "requests" in imports and ("requests.get(" in all_code or "requests.post(" in all_code or "api_url" in all_code_lower or "api_key" in all_code_lower):
        features["apis"].append("External API Integration")
    if "google" in imports or "from google" in all_code_lower:
        features["apis"].append("Google APIs")
    # Only detect Instagram if actually using Instagram API (not just word "insta")
    if "instagrapi" in imports or "instagram_private_api" in imports or "graph.instagram.com" in all_code_lower:
        features["apis"].append("Instagram Integration")
    
    # Detect authentication - be specific
    if "jwt" in imports or "pyjwt" in imports or "import jwt" in all_code_lower:
        features["auth"].append("JWT Authentication")
    if "authlib" in imports or "auth0" in imports or "oauth2" in all_code_lower:
        features["auth"].append("OAuth")
    if ("flask_login" in imports or "django.contrib.auth" in imports) and ("def login" in all_code_lower):
        features["auth"].append("Session-based Auth")
    
    # Notable features - be specific
    if ("playtest" in all_code_lower and "def" in all_code_lower) or "beta_test" in all_code_lower:
        features["notable_features"].append("Beta Testing/Playtest System")
    if "smtplib" in imports or "sendgrid" in imports or "mailgun" in imports:
        features["notable_features"].append("Email Functionality")
    if "apscheduler" in imports or "celery.beat" in all_code_lower:
        features["notable_features"].append("Scheduled Tasks")
    if "websockets" in imports or "socketio" in imports or "socket.io" in all_code_lower:
        features["notable_features"].append("Real-time Communication")
    if "admin" in all_code_lower and "dashboard" in all_code_lower:
        features["notable_features"].append("Admin Dashboard")
    if "pytest" in imports or "unittest" in imports:
        features["notable_features"].append("Automated Testing")
    if "selenium" in imports or "playwright" in imports:
        features["notable_features"].append("Browser Automation")
    if "pandas" in imports or "numpy" in imports:
        features["notable_features"].append("Data Analysis")
    if "matplotlib" in imports or "plotly" in imports:
        features["notable_features"].append("Data Visualization")
    if "unity" in all_code_lower or "unityengine" in all_code_lower:
        features["notable_features"].append("Unity Game Engine")
    if "payment" in all_code_lower or "checkout" in all_code_lower:
        features["notable_features"].append("Payment Processing")
    if "ci/cd" in all_code_lower or "github actions" in all_code_lower or ".github/workflows" in all_code_lower:
        features["notable_features"].append("CI/CD Pipeline")
    
    return features

# ---------------- analyze ----------------
def analyze_repo(repo, sample_limit=8, progress_cb=None):
    send_progress(progress_cb, "analyze_repo.start", 0, f"Analyzing {repo.full_name}")
    meta = {
        "name": repo.name,
        "full_name": repo.full_name,
        "private": repo.private,
        "description": repo.description or "",
        "language": repo.language,
        "stars": repo.stargazers_count,
        "forks": repo.forks_count,
        "size_kb": repo.size,
    }

    file_count = 0
    loc = 0
    imports = Counter()
    todo_count = 0
    samples = []
    stats = {"skipped_dirs": 0, "skipped_files": 0}
    readme_content = None

    for f in walk_repo_files(repo, "", stats):
        file_count += 1
        # Progress update every 5 files for more frequent updates
        if file_count % 5 == 0:
            send_progress(progress_cb, "analyze_repo.files", 30, f"📄 Scanning {repo.name}: {file_count} files...")
        try:
            lines = f["content"].splitlines()
            loc += len(lines)
            
            # Capture README if found
            if f["path"].lower() in ["readme.md", "readme.txt", "readme"]:
                readme_content = f["content"][:2000]  # First 2000 chars
                send_progress(progress_cb, "found_readme", 35, f"📖 Found existing README in {repo.name}")
            
            if len(samples) < sample_limit:
                samples.append({"path": f["path"], "snippet": "\n".join(lines[:40])})
            for m in IMPORT_RE.findall(f["content"][:3000]):
                imports[m.split(".")[0]] += 1
            if re.search(r"\b(TODO|FIXME|WIP|UNFINISHED)\b", f["content"], re.IGNORECASE):
                todo_count += 1
        except Exception:
            continue

    # Extract features from code
    send_progress(progress_cb, "analyze_features", 60, f"🔍 Analyzing code patterns in {repo.name}...")
    features = extract_features_from_code(samples, dict(imports))
    
    # Log detected features
    detected = []
    if features.get('functionality', {}).get('endpoints'):
        detected.append(f"{len(features['functionality']['endpoints'])} endpoints")
    if features.get('functionality', {}).get('business_logic'):
        detected.append(f"{len(features['functionality']['business_logic'])} capabilities")
    if detected:
        send_progress(progress_cb, "features_found", 70, f"✨ Found: {', '.join(detected)} in {repo.name}")
    
    meta.update({
        "file_count": file_count,
        "loc": loc,
        "imports": dict(imports.most_common(12)),
        "todo_count": todo_count,
        "samples": samples,
        "skipped_dirs": stats["skipped_dirs"],
        "skipped_files": stats["skipped_files"],
        "features": features,
        "readme_content": readme_content
    })

    status = "Archive"
    if (file_count >= 3 and loc >= 200) or meta["stars"] > 3:
        status = "Portfolio-Ready"
    if todo_count > 0 or loc < 200:
        status = "Prototype"
    meta["status"] = status

    # Report what was filtered
    skip_msg = f"✅ Analyzed {repo.full_name}: {file_count} files, {loc:,} LOC"
    if stats["skipped_dirs"] > 0 or stats["skipped_files"] > 0:
        skip_msg += f" (filtered {stats['skipped_dirs']} dirs, {stats['skipped_files']} files)"
    send_progress(progress_cb, "analyze_repo.done", 100, skip_msg)
    return meta

# ---------------- README generation ----------------
def generate_portfolio_readme(repo_meta, existing_readme=None, openai_key=None):
    """Generate a comprehensive portfolio-ready README for a repository."""
    name = repo_meta.get('name', 'Project')
    desc = repo_meta.get('description') or 'A software project showcasing development skills'
    lang = repo_meta.get('language') or 'Multiple'
    status = repo_meta.get('status', 'In Development')
    file_count = repo_meta.get('file_count', 0)
    loc = repo_meta.get('loc', 0)
    imports = list(repo_meta.get('imports', {}).keys())
    stars = repo_meta.get('stars', 0)
    features = repo_meta.get('features', {})
    
    # Build comprehensive tech stack
    tech_stack = []
    if lang:
        tech_stack.append(lang)
    
    # Add frameworks
    for fw in features.get('frameworks', []):
        if fw not in tech_stack:
            tech_stack.append(fw)
    
    # Add key imports
    for imp in imports[:5]:
        if imp not in tech_stack and imp not in ['os', 'sys', 'json', 'time', 'datetime']:
            tech_stack.append(imp)
    
    # Generate feature-rich description based on actual code analysis
    description_parts = []
    functionality = features.get('functionality', {})
    business_logic = functionality.get('business_logic', [])
    endpoints = functionality.get('endpoints', [])
    
    # Extract all feature types
    app_types = features.get('app_type', [])
    apis = features.get('apis', [])
    databases = features.get('database', [])
    auth_methods = features.get('auth', [])
    notable = features.get('notable_features', [])
    deployment = features.get('deployment', [])
    
    # App type - factual
    if app_types:
        description_parts.append(f"{app_types[0]}")
    elif desc:
        description_parts.append(desc)
    else:
        description_parts.append(f"{lang} application")
    
    # Core capabilities
    if business_logic:
        capabilities = []
        for bl in business_logic[:4]:
            capabilities.append(bl.lower())
        if capabilities:
            description_parts.append(f"Implements {', '.join(capabilities)}")
    
    # API endpoints
    if endpoints:
        description_parts.append(f"Exposes {len(endpoints)} API endpoint{'s' if len(endpoints) > 1 else ''}")
    
    # Tech stack
    stack_parts = []
    if databases:
        stack_parts.append(databases[0])
    if apis:
        stack_parts.extend(apis[:2])
    if stack_parts:
        description_parts.append(f"Built with {', '.join(stack_parts)}")
    
    # Deployment
    if deployment:
        description_parts.append(f"Deployed to {deployment[0]}")
    
    full_description = ". ".join(description_parts) + "."
    
    # Optionally enhance with OpenAI
    enhanced_description = full_description
    ai_used = False
    if OPENAI_AVAILABLE and openai_key:
        try:
            import openai as openai_module
            client = openai_module.OpenAI(api_key=openai_key)
            
            # Build rich context for AI
            user_flows = functionality.get('user_flows', [])
            docstrings = functionality.get('docstrings', [])
            comments = functionality.get('comments', [])
            samples = repo_meta.get('samples', [])
            readme_content = repo_meta.get('readme_content', '')
            
            # Extract landing page and component content from frontend files
            landing_page_text = []
            for sample in samples[:12]:
                path = sample.get('path', '').lower()
                snippet = sample.get('snippet', '')
                
                # HTML files
                if '.html' in path:
                    text_matches = re.findall(r'<h[1-6][^>]*>([^<]+)</h[1-6]>|<p[^>]*>([^<]+)</p>|<title>([^<]+)</title>|<meta[^>]*content="([^"]+)"', snippet)
                    for match in text_matches:
                        text = ''.join(match).strip()
                        if text and len(text) > 15 and not text.startswith('{'):
                            landing_page_text.append(text)
                
                # JSX/TSX files - extract string literals from components
                elif '.jsx' in path or '.tsx' in path:
                    # Extract string literals in JSX
                    jsx_strings = re.findall(r'>([^<>{}\n]+)<|"([^"]{20,})"', snippet)
                    for match in jsx_strings:
                        text = ''.join(match).strip()
                        if text and len(text) > 15 and not any(c in text for c in ['=', '{', '}', '(', ')']):
                            landing_page_text.append(text)
            
            # Extract existing README info if available
            readme_info = ""
            if readme_content:
                readme_info = f"\nEXISTING README:\n{readme_content[:400]}\n"
            
            landing_info = ""
            if landing_page_text:
                landing_info = f"\nLANDING PAGE CONTENT:\n{chr(10).join('- ' + text[:80] for text in landing_page_text[:4])}\n"
            
            context = f"""Project: {name}
Language: {lang}
Type: {', '.join(app_types) if app_types else 'Application'}
Repo Description: {desc}
{readme_info}{landing_info}
STACK:
- APIs: {', '.join(apis[:3]) if apis else 'None'}
- Database: {', '.join(databases) if databases else 'None'}
- Deployment: {', '.join(deployment) if deployment else 'None'}

USER ACTIONS:
{chr(10).join('- ' + flow for flow in user_flows[:6]) if user_flows else '- Not detected'}

CODE SAMPLES:
{chr(10).join('- ' + doc[:80] for doc in docstrings[:2]) if docstrings else '- No docs'}

Generate a FACTUAL 2-3 sentence technical summary. NOT marketing copy. Just state:
1. What this application is (type/purpose)
2. What it does (main features/functionality)
3. What it's built with (tech stack)

Write like a technical report, not a sales pitch. No words like "empowers", "seamlessly", "dynamic", "comprehensive". Just facts."""
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a technical documentation writer. Write factual, concise descriptions. No marketing language. No hype. Just state what the application is, what it does, and what it's built with. Write like you're reporting to another developer, not selling to a customer."},
                    {"role": "user", "content": context}
                ],
                max_tokens=150,
                temperature=0.5
            )
            
            ai_desc = response.choices[0].message.content.strip()
            if ai_desc and len(ai_desc) > 20:
                enhanced_description = ai_desc
                ai_used = True
        except Exception as e:
            # Log error but fall back to heuristic description
            print(f"OpenAI error for {name}: {str(e)}")
            pass
    
    # Build README sections
    sections = []
    
    # Header
    sections.append(f"# {name}")
    sections.append("")
    
    # Description (use AI-enhanced if available)
    sections.append(enhanced_description)
    sections.append("")
    
    # Badges
    if stars > 0:
        sections.append(f"![Stars](https://img.shields.io/badge/stars-{stars}-yellow)")
    if lang:
        sections.append(f"![Language](https://img.shields.io/badge/language-{lang.replace(' ', '%20')}-blue)")
    sections.append(f"![Status](https://img.shields.io/badge/status-{status.replace(' ', '%20')}-green)")
    sections.append("")
    
    # User Experience - what users can actually DO
    user_flows = functionality.get('user_flows', [])
    if user_flows:
        sections.append("## 👤 User Experience")
        sections.append("")
        sections.append("**What users can do:**")
        for flow in user_flows[:8]:
            sections.append(f"- {flow}")
        sections.append("")
    
    # Functionality section - what the code actually does
    if business_logic or endpoints:
        sections.append("## 🎯 Functionality")
        sections.append("")
        
        if business_logic:
            sections.append("**Core Capabilities:**")
            for logic in list(set(business_logic))[:5]:  # Dedupe and limit
                sections.append(f"- {logic}")
            sections.append("")
        
        if endpoints:
            sections.append("**API Endpoints:**")
            for ep in endpoints[:6]:  # Show first 6 endpoints
                sections.append(f"- `{ep['path']}` ({ep['framework']})")
            if len(endpoints) > 6:
                sections.append(f"- ...and {len(endpoints) - 6} more endpoints")
            sections.append("")
    
    # Features section
    if any([app_types, apis, databases, auth_methods, notable]):
        sections.append("## ✨ Key Features")
        sections.append("")
        if app_types:
            sections.append(f"- **Application Type:** {', '.join(app_types)}")
        if apis:
            sections.append(f"- **Integrations:** {', '.join(apis)}")
        if databases:
            sections.append(f"- **Database:** {', '.join(databases)}")
        if auth_methods:
            sections.append(f"- **Authentication:** {', '.join(auth_methods)}")
        if notable:
            for feature in notable:
                sections.append(f"- {feature}")
        sections.append("")
    
    # Tech Stack
    if tech_stack:
        sections.append("## 🛠️ Tech Stack")
        sections.append("")
        for tech in tech_stack[:8]:
            sections.append(f"- {tech}")
        sections.append("")
    
    # Deployment
    if deployment:
        sections.append("## 🚀 Deployment")
        sections.append("")
        sections.append(f"This project is configured for deployment on **{', '.join(deployment)}**.")
        sections.append("")
    
    # Project Stats
    sections.append("## 📊 Project Statistics")
    sections.append("")
    sections.append(f"- **Total Files:** {file_count}")
    sections.append(f"- **Lines of Code:** {loc:,}")
    sections.append(f"- **Primary Language:** {lang}")
    sections.append(f"- **Development Status:** {status}")
    sections.append("")
    
    # Footer
    sections.append("---")
    sections.append("")
    if ai_used:
        sections.append("*This README was auto-generated with AI assistance to showcase this project as part of a development portfolio.*")
    else:
        sections.append("*This README was auto-generated to showcase this project as part of a development portfolio.*")
    
    return "\n".join(sections)

def commit_readme_to_repo(repo, readme_content, message="docs: Update README with portfolio information"):
    """Commit README.md to the repository.
    
    Args:
        repo: PyGithub Repository object
        readme_content: String content for README.md
        message: Commit message
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Try to get existing README
        try:
            readme_file = repo.get_contents("README.md")
            # Update existing
            repo.update_file(
                path="README.md",
                message=message,
                content=readme_content,
                sha=readme_file.sha,
                branch=repo.default_branch
            )
            return True
        except Exception:
            # Create new README
            repo.create_file(
                path="README.md",
                message=message,
                content=readme_content,
                branch=repo.default_branch
            )
            return True
    except Exception as e:
        # If we can't write (permissions, etc.), just return False
        return False

# ---------------- full scan ----------------
def run_full_scan(config, progress_callback=None):
    gh_token = config.get("github_token")
    openai_key = config.get("openai_key")
    use_ai = config.get("use_ai", False)
    include_private = config.get("include_private", True)
    
    # Only use OpenAI if both key exists and use_ai is enabled
    effective_openai_key = openai_key if use_ai else None
    
    # Use config output_dir or fallback to default
    base_output = config.get("output_dir", Path.home() / "codefolio_output")
    output_dir = Path(base_output) / "summaries"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    send_progress(progress_callback, "init", 0, f"Output directory: {output_dir}")

    gh = Github(gh_token)
    all_repos = list(gh.get_user().get_repos())
    
    # Filter repos
    filtered_repos = []
    for r in all_repos:
        # Skip private repos if not included
        if not include_private and r.private:
            continue
        # Skip archived repos
        if r.archived:
            send_progress(progress_callback, "skip_repo", 0, f"Skipping archived: {r.full_name}")
            continue
        # Skip forks (optional - can be configured)
        # if r.fork:
        #     continue
        filtered_repos.append(r)
    
    total_repos = len(filtered_repos)
    send_progress(progress_callback, "scan_start", 0, f"Found {total_repos} repos to scan")

    # Check if we should commit to GitHub or just save locally
    auto_commit = config.get("auto_commit", False)
    dry_run = config.get("dry_run", True)
    
    for idx, repo in enumerate(filtered_repos):
        repo_pct = int((idx+1)/total_repos*100)
        send_progress(progress_callback, "scan_repo", repo_pct, f"🔄 [{idx+1}/{total_repos}] Starting {repo.full_name}...")
        
        try:
            # Analyze repo
            send_progress(progress_callback, "analyzing", repo_pct, f"📊 [{idx+1}/{total_repos}] Analyzing {repo.name}...")
            meta = analyze_repo(repo, progress_cb=progress_callback)
            
            # Skip repos with no meaningful content
            if meta.get("file_count", 0) == 0:
                send_progress(progress_callback, "skip_empty", repo_pct, f"⏭️  [{idx+1}/{total_repos}] Skipped {repo.name} - no files found")
                continue
            
            # Generate portfolio-ready README
            send_progress(progress_callback, "generating", repo_pct, f"📝 [{idx+1}/{total_repos}] Generating README for {repo.name}...")
            
            # Check if using OpenAI
            use_ai_msg = ""
            if OPENAI_AVAILABLE and effective_openai_key:
                use_ai_msg = " (with AI enhancement)"
                send_progress(progress_callback, "ai_enhance", repo_pct, f"🤖 [{idx+1}/{total_repos}] Using OpenAI to enhance {repo.name} description...")
            
            readme_content = generate_portfolio_readme(meta, openai_key=effective_openai_key)
            
            # Save local copy
            filename = output_dir / f"{repo.name.replace(' ','_')}.md"
            send_progress(progress_callback, "saving", repo_pct, f"💾 [{idx+1}/{total_repos}] Saving {filename.name}...")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(readme_content)
            
            # Optionally commit to GitHub
            commit_status = ""
            if auto_commit and not dry_run:
                send_progress(progress_callback, "committing", repo_pct, f"📤 [{idx+1}/{total_repos}] Committing to {repo.name}...")
                success = commit_readme_to_repo(repo, readme_content)
                if success:
                    commit_status = " ✅ Committed to GitHub"
                else:
                    commit_status = " ⚠️  GitHub commit failed"
            elif dry_run:
                commit_status = " 🔍 (dry run)"
            
            # Show detected features in completion message
            features = meta.get('features', {})
            functionality = features.get('functionality', {})
            endpoints_count = len(functionality.get('endpoints', []))
            logic_count = len(functionality.get('business_logic', []))
            
            feature_info = ""
            if endpoints_count > 0 or logic_count > 0:
                feature_info = f" | {endpoints_count} endpoints, {logic_count} features"
            
            send_progress(progress_callback, "repo_complete", repo_pct, 
                         f"✅ [{idx+1}/{total_repos}] {repo.name}: {meta.get('file_count')} files, {meta.get('loc'):,} LOC{feature_info}{commit_status}")
        except Exception as e:
            send_progress(progress_callback, "error", repo_pct, f"❌ [{idx+1}/{total_repos}] Error with {repo.name}: {str(e)}")
            continue
    
    # Final summary
    send_progress(progress_callback, "complete", 100, f"🎉 Scan complete! Processed {total_repos} repositories. Check {output_dir}")
