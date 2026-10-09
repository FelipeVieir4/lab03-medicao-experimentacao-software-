from datetime import datetime
import numpy as np

def parse_date(date_str):
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")

def calculate_cfr_proxy_ci(workflow_runs):
    """
    Calcula Change Failure Rate (CFR) usando proxy de CI.
    Fórmula: nº de falhas / (nº de falhas + nº de sucessos)
    """
    failures = 0
    successes = 0
    
    failure_statuses = {'failure', 'timed_out', 'startup_failure'}
    
    for run in workflow_runs:
        conclusion = run.get('conclusion')
        if conclusion == 'success':
            successes += 1
        elif conclusion in failure_statuses:
            failures += 1
            
    total = failures + successes
    if total == 0:
        return None
        
    return failures / total

def calculate_recovery_time(workflow_runs):
    """
    Calcula Tempo de Recuperação.
    Mede a mediana de todos os episódios de falha de todos os workflows.
    """
    workflows = {}
    for run in workflow_runs:
        wf_id = run.get('workflow_id')
        if wf_id not in workflows:
            workflows[wf_id] = []
        workflows[wf_id].append(run)
        
    recovery_times_hours = []
    censored_count = 0
    total_episodes = 0
    
    failure_statuses = {'failure', 'timed_out', 'startup_failure'}
    
    for wf_id, runs in workflows.items():
        # Ordena cronologicamente
        runs.sort(key=lambda x: parse_date(x.get('created_at')))
        
        in_episode = False
        episode_start_time = None
        
        for run in runs:
            conclusion = run.get('conclusion')
            
            # Ignorar casos neutros
            if conclusion not in failure_statuses and conclusion != 'success':
                continue
                
            if not in_episode:
                if conclusion in failure_statuses:
                    in_episode = True
                    episode_start_time = parse_date(run.get('run_started_at') or run.get('created_at'))
                    total_episodes += 1
            else:
                if conclusion == 'success':
                    # Episódio terminou
                    success_time = parse_date(run.get('updated_at'))
                    if success_time and episode_start_time:
                        delta = success_time - episode_start_time
                        recovery_times_hours.append(delta.total_seconds() / 3600.0)
                    in_episode = False
        
        if in_episode:
            censored_count += 1
            
    median_recovery_time = np.median(recovery_times_hours) if recovery_times_hours else None
    censored_ratio = censored_count / total_episodes if total_episodes > 0 else 0
    
    return {
        'median_recovery_time_hours': median_recovery_time,
        'censored_ratio': censored_ratio,
        'total_episodes': total_episodes
    }

def get_dora_classification_recovery_time(recovery_time_hours):
    """Classificação DORA para tempo de recuperação."""
    if recovery_time_hours is None:
        return None
    if recovery_time_hours < 1:
        return 'Elite'
    elif recovery_time_hours < 24:
        return 'High'
    elif recovery_time_hours < 168: # 7 dias
        return 'Medium'
    else:
        return 'Low'

def get_dora_classification_cfr(cfr):
    """Classificação DORA para Change Failure Rate."""
    if cfr is None:
        return None
    if cfr <= 0.15:
        return 'Elite'
    elif cfr <= 0.30:
        return 'High'
    elif cfr <= 0.45:
        return 'Medium'
    else:
        return 'Low'
