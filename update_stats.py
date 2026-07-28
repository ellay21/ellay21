import os
import re
import sys
import json
import calendar
import requests
from datetime import datetime, timezone

# Configuration
DEFAULT_USERNAME = "ellay21"
CACHE_FILE = ".cache_stats.json"

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"code_frequency": {}, "stats": {}}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save cache: {e}")

def calculate_age():
    birth_date_env = os.getenv("BIRTH_DATE")
    
    if not birth_date_env:
        print("Notice: BIRTH_DATE secret variable not set (format YYYY-MM).")
        return "N/A"

    try:
        parts = birth_date_env.split("-")
        year, month = int(parts[0]), int(parts[1])
    except Exception:
        print("Notice: Invalid BIRTH_DATE format. Use YYYY-MM.")
        return "N/A"

    today = datetime.now(timezone.utc).date()
    
    years = today.year - year
    months = today.month - month
    
    if months < 0:
        years -= 1
        months += 12
        
    return f"{years} years, {months} months"

def fetch_github_stats(username, token):
    headers = {"Authorization": f"bearer {token}"} if token else {}
    graphql_url = "https://api.github.com/graphql"
    cache = load_cache()
    cached_stats = cache.get("stats", {})
    
    stats = {
        "repo_data": cached_stats.get("repo_data", "0"),
        "contrib_data": cached_stats.get("contrib_data", "0"),
        "commit_data": cached_stats.get("commit_data", "0"),
        "follower_data": cached_stats.get("follower_data", "0"),
        "loc_data": cached_stats.get("loc_data", "0"),
        "loc_add": cached_stats.get("loc_add", "0"),
        "loc_del": cached_stats.get("loc_del", "0"),
    }
    
    query = """
    query($username: String!) {
      user(login: $username) {
        login
        followers {
          totalCount
        }
        repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST]) {
          totalCount
        }
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
        repositories(first: 100, ownerAffiliations: OWNER) {
          totalCount
          nodes {
            name
            isPrivate
            defaultBranchRef {
              target {
                ... on Commit {
                  history {
                    totalCount
                  }
                }
              }
            }
          }
        }
      }
      viewer {
        login
        followers {
          totalCount
        }
        repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST]) {
          totalCount
        }
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
        repositories(first: 100, ownerAffiliations: OWNER) {
          totalCount
          nodes {
            name
            isPrivate
            defaultBranchRef {
              target {
                ... on Commit {
                  history {
                    totalCount
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    if token:
        try:
            response = requests.post(graphql_url, json={"query": query, "variables": {"username": username}}, headers=headers, timeout=15)
            if response.status_code == 200:
                res_json = response.json()
                data = res_json.get("data", {})
                viewer_data = data.get("viewer")
                user_data = data.get("user")
                
                target_data = user_data
                if viewer_data and viewer_data.get("login", "").lower() == username.lower():
                    target_data = viewer_data
                    print(f"Authenticated as viewer: '{username}' (includes private repos & commits)")
                else:
                    print(f"Querying GitHub user profile: '{username}'")
                    
                if target_data:
                    stats["follower_data"] = f"{target_data['followers']['totalCount']:,}"
                    stats["contrib_data"] = f"{target_data['repositoriesContributedTo']['totalCount']:,}"
                    
                    repos = target_data["repositories"]["nodes"]
                    stats["repo_data"] = f"{target_data['repositories']['totalCount']:,}"
                    
                    history_commits = 0
                    for repo in repos:
                        branch = repo.get("defaultBranchRef")
                        if branch and branch.get("target"):
                            history_commits += branch["target"].get("history", {}).get("totalCount", 0)
                            
                    contrib_coll = target_data.get("contributionsCollection", {})
                    contrib_commits = contrib_coll.get("totalCommitContributions", 0) + contrib_coll.get("restrictedContributionsCount", 0)
                    
                    total_commits = max(history_commits, contrib_commits)
                    stats["commit_data"] = f"{total_commits:,}"
                    
                    total_add = 0
                    total_del = 0
                    for repo in repos:
                        repo_name = repo["name"]
                        cached_cf = cache.get("code_frequency", {}).get(repo_name)
                        
                        stats_url = f"https://api.github.com/repos/{username}/{repo_name}/stats/code_frequency"
                        repo_add = 0
                        repo_del = 0
                        fetched = False
                        
                        try:
                            code_freq = requests.get(stats_url, headers=headers, timeout=5)
                            if code_freq.status_code == 200 and isinstance(code_freq.json(), list):
                                for week in code_freq.json():
                                    if len(week) >= 3:
                                        repo_add += week[1]
                                        repo_del += abs(week[2])
                                cache.setdefault("code_frequency", {})[repo_name] = {"add": repo_add, "del": repo_del}
                                fetched = True
                        except Exception:
                            pass
                            
                        if not fetched and cached_cf:
                            repo_add = cached_cf.get("add", 0)
                            repo_del = cached_cf.get("del", 0)
                            
                        total_add += repo_add
                        total_del += repo_del

                    stats["loc_add"] = f"{total_add:,}"
                    stats["loc_del"] = f"{total_del:,}"
                    net_loc = total_add - total_del
                    stats["loc_data"] = f"{net_loc:,}"

                    cache["stats"] = stats
                    save_cache(cache)
                    return stats
        except Exception as e:
            print(f"GraphQL request error: {e}")

    # Fallback to REST API if token is missing or GraphQL failed
    print(f"Fetching REST API stats for user '{username}'...")
    try:
        user_res = requests.get(f"https://api.github.com/users/{username}", headers=headers, timeout=10)
        if user_res.status_code == 200:
            u_data = user_res.json()
            if isinstance(u_data, dict) and "message" not in u_data:
                stats["repo_data"] = f"{u_data.get('public_repos', 0):,}"
                stats["follower_data"] = f"{u_data.get('followers', 0):,}"
        
        repos_res = requests.get(f"https://api.github.com/users/{username}/repos?per_page=100", headers=headers, timeout=10)
        if repos_res.status_code == 200:
            public_repos = repos_res.json()
            if isinstance(public_repos, list):
                total_add = 0
                total_del = 0
                total_commits = 0
                for r in public_repos:
                    repo_name = r.get("name")
                    cached_cf = cache.get("code_frequency", {}).get(repo_name)
                    
                    stats_url = f"https://api.github.com/repos/{username}/{repo_name}/stats/code_frequency"
                    repo_add = 0
                    repo_del = 0
                    fetched = False
                    
                    try:
                        code_freq = requests.get(stats_url, headers=headers, timeout=5)
                        if code_freq.status_code == 200 and isinstance(code_freq.json(), list):
                            for week in code_freq.json():
                                if len(week) >= 3:
                                    repo_add += week[1]
                                    repo_del += abs(week[2])
                            cache.setdefault("code_frequency", {})[repo_name] = {"add": repo_add, "del": repo_del}
                            fetched = True
                    except Exception:
                        pass
                        
                    if not fetched and cached_cf:
                        repo_add = cached_cf.get("add", 0)
                        repo_del = cached_cf.get("del", 0)
                        
                    total_add += repo_add
                    total_del += repo_del
                        
                    commits_url = f"https://api.github.com/repos/{username}/{repo_name}/commits?per_page=1"
                    try:
                        c_res = requests.get(commits_url, headers=headers, timeout=5)
                        if c_res.status_code == 200 and "Link" in c_res.headers:
                            match = re.search(r'page=(\d+)>; rel="last"', c_res.headers["Link"])
                            if match:
                                total_commits += int(match.group(1))
                    except Exception:
                        pass

                if total_add > 0 or total_del > 0:
                    stats["loc_add"] = f"{total_add:,}"
                    stats["loc_del"] = f"{total_del:,}"
                    stats["loc_data"] = f"{total_add - total_del:,}"
                if total_commits > 0:
                    stats["commit_data"] = f"{total_commits:,}"
    except Exception as e:
        print(f"Error fetching REST API stats: {e}")

    cache["stats"] = stats
    save_cache(cache)
    return stats

def update_svg_file(filepath, replacements):
    if not os.path.exists(filepath):
        return False
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    updated = False
    for key, value in replacements.items():
        pattern = re.compile(rf'(id="{key}"[^>]*>)([^<]*)(</tspan>)')
        if pattern.search(content):
            content = pattern.sub(rf'\g<1>{value}\g<3>', content)
            updated = True
            
    if updated:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated {filepath}")
        return True
    return False

def main():
    username = os.getenv("GH_USERNAME", DEFAULT_USERNAME)
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    
    print("Calculating exact age...")
    age_str = calculate_age()
    print(f"Age: {age_str}")
    
    print(f"Fetching GitHub stats for user '{username}'...")
    stats = fetch_github_stats(username, token)
    stats["age_data"] = age_str
    
    print("Stats summary:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
        
    svg_files = ["dark_mode.svg", "light_mode.svg"]
    for svg in svg_files:
        if os.path.exists(svg):
            update_svg_file(svg, stats)

if __name__ == "__main__":
    main()
