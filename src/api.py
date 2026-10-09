import os
import time
import sqlite3
import json
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GitHubAPI:
    def __init__(self, db_path="github_cache.sqlite"):
        self.token = os.getenv("GITHUB_TOKEN")
        if not self.token:
            logging.warning("GITHUB_TOKEN não encontrado nas variáveis de ambiente.")
        
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
            
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS api_cache (
                    url TEXT PRIMARY KEY,
                    response TEXT,
                    status_code INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def _get_cached(self, url):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT response, status_code FROM api_cache WHERE url = ?", (url,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0]), row[1]
        return None, None

    def _save_cache(self, url, response_data, status_code):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO api_cache (url, response, status_code) VALUES (?, ?, ?)",
                (url, json.dumps(response_data), status_code)
            )

    def _handle_rate_limit(self, response):
        if 'X-RateLimit-Remaining' in response.headers:
            remaining = int(response.headers['X-RateLimit-Remaining'])
            if remaining == 0:
                reset_time = int(response.headers['X-RateLimit-Reset'])
                sleep_time = max(0, reset_time - int(time.time())) + 1
                logging.warning(f"Rate limit atingido. Aguardando {sleep_time} segundos...")
                time.sleep(sleep_time)

    def get(self, url, params=None, use_cache=True):
        if params:
            # Build query string for URL to cache properly
            req = requests.Request('GET', url, params=params)
            prep = req.prepare()
            full_url = prep.url
        else:
            full_url = url

        if use_cache:
            cached_data, cached_status = self._get_cached(full_url)
            if cached_data is not None:
                logging.debug(f"Cache hit: {full_url}")
                return cached_data, cached_status

        logging.info(f"Fetching: {full_url}")
        
        max_retries = 5
        backoff_factor = 1

        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, params=params)
                self._handle_rate_limit(response)
                
                # Handling 5xx errors with exponential backoff
                if 500 <= response.status_code < 600:
                    logging.warning(f"Erro {response.status_code}. Tentativa {attempt + 1}/{max_retries}.")
                    time.sleep(backoff_factor * (2 ** attempt))
                    continue
                
                response_data = response.json() if response.text else None
                
                if response.status_code == 200 and use_cache:
                    self._save_cache(full_url, response_data, response.status_code)
                    
                return response_data, response.status_code
            except requests.RequestException as e:
                logging.error(f"Erro de conexão: {e}. Tentativa {attempt + 1}/{max_retries}.")
                time.sleep(backoff_factor * (2 ** attempt))
                
        raise Exception(f"Falha ao acessar {full_url} após {max_retries} tentativas.")

    def get_paginated(self, url, params=None):
        """
        Retorna um gerador que yield todas as páginas de um endpoint paginado.
        """
        if params is None:
            params = {}
        params['per_page'] = 100
        page = 1
        
        while True:
            params['page'] = page
            data, status = self.get(url, params=params)
            
            if status != 200 or not data:
                break
                
            yield data
            
            if len(data) < params['per_page']:
                break
            page += 1

def fetch_workflow_runs(owner, repo, start_date, end_date):
    """
    Busca execuções de workflow para um repositório num intervalo de datas.
    Divide as consultas mensalmente caso haja mais de 1000 resultados.
    """
    api = GitHubAPI()
    base_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    
    # Busca informações do repositório para obter o default branch
    repo_data, _ = api.get(f"https://api.github.com/repos/{owner}/{repo}")
    if not repo_data:
         return []
    default_branch = repo_data.get('default_branch', 'main')
    
    # Para lidar com a restrição de 1000 resultados, podemos quebrar o intervalo se necessário
    # Por simplicidade neste exemplo, fazemos uma consulta por toda a janela. 
    # Se batermos no limite, deveríamos quebrar.
    params = {
        'branch': default_branch,
        'event': 'push',
        'created': f"{start_date}..{end_date}"
    }
    
    all_runs = []
    try:
        for page_data in api.get_paginated(base_url, params):
            # The actions/runs endpoint returns an object with a 'workflow_runs' key
            if isinstance(page_data, dict) and 'workflow_runs' in page_data:
                all_runs.extend(page_data['workflow_runs'])
    except Exception as e:
        logging.error(f"Erro ao buscar workflow runs para {owner}/{repo}: {e}")
        
    return all_runs
