#!/usr/bin/env python3
"""
一次性迁移脚本：从 Firestore + Firebase Storage 把项目元数据 + 音频拉到本地。

输出目录布局（直接对应 ECS Docker volume `ai-srt-dubbing_ai-dubbing-projects`）：

  ./migrated/.ai_dubbing_projects/
    projects_index.json
    data/{project_id}.pkl
    audio/users/{uid}/projects/{pid}/audio/{stage}/{sid}.mp3
    audio/users/{uid}/projects/{pid}/output/{filename}

使用：
    python3 utils/scripts/migrate_firestore_to_local.py [USER_ID ...]
    # 留空 USER_ID 表示用默认的 DYJ XYC
"""
import os
import sys
import time
from pathlib import Path

# 让脚本能 import 上级目录的模块
THIS = Path(__file__).resolve()
PROJECT_ROOT = THIS.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import firebase_admin
from firebase_admin import credentials, firestore, storage

from models.project_dto import ProjectDTO
from utils.project_manager import ProjectManager


def main(user_ids):
    out_root = Path('./migrated/.ai_dubbing_projects').resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    audio_root = out_root / 'audio'
    audio_root.mkdir(parents=True, exist_ok=True)

    # Firebase 初始化
    cred = credentials.Certificate('firebase-credentials.json')
    try:
        firebase_admin.initialize_app(cred, {'storageBucket': 'ai-dubbing-system-dev.firebasestorage.app'})
    except ValueError:
        pass
    db = firestore.client()
    bucket = storage.bucket()

    # 用 ProjectManager 写入（自动维护 index）
    pm = ProjectManager(projects_dir=str(out_root))

    total_projects = 0
    total_files = 0
    total_bytes = 0
    failed = []

    for uid in user_ids:
        print(f"\n=== USER: {uid} ===")
        # 1) 拉 Firestore 项目元数据
        docs = list(db.collection('users').document(uid).collection('projects').stream())
        print(f"  Firestore docs: {len(docs)}")
        for d in docs:
            try:
                data = d.to_dict() or {}
                if 'id' not in data:
                    data['id'] = d.id  # 保留 doc id
                dto = ProjectDTO.from_firestore_dict(data)
                # 标记 owner_id，避免老数据缺失
                if not dto.owner_id:
                    dto.owner_id = uid
                if pm.save_project(dto):
                    total_projects += 1
                    print(f"    ✓ {dto.id}  {dto.name}  ({dto.processing_stage})")
                else:
                    failed.append((uid, dto.id, "save_project returned False"))
            except Exception as e:
                failed.append((uid, d.id, str(e)[:100]))
                print(f"    ✗ {d.id}  failed: {e}")

        # 2) 拉 Firebase Storage 该用户的所有 blob
        prefix = f'users/{uid}/projects/'
        blobs = list(bucket.list_blobs(prefix=prefix))
        print(f"  Storage blobs: {len(blobs)}")
        t0 = time.time()
        last_log = 0
        for i, blob in enumerate(blobs, 1):
            local = audio_root / blob.name
            local.parent.mkdir(parents=True, exist_ok=True)
            if local.exists() and local.stat().st_size == (blob.size or 0):
                # already downloaded with matching size, skip
                pass
            else:
                try:
                    blob.download_to_filename(str(local))
                except Exception as e:
                    failed.append((uid, blob.name, str(e)[:100]))
                    continue
            total_files += 1
            total_bytes += blob.size or 0
            if time.time() - last_log > 3:
                print(f"    ... {i}/{len(blobs)}  ({total_bytes/1024/1024:.1f} MB)")
                last_log = time.time()
        print(f"  user done: {len(blobs)} files in {time.time()-t0:.1f}s")

    print(f"\n==== SUMMARY ====")
    print(f"Projects migrated: {total_projects}")
    print(f"Audio files downloaded: {total_files}")
    print(f"Total size: {total_bytes/1024/1024:.1f} MB")
    print(f"Index file: {out_root / 'projects_index.json'}")
    print(f"Failures: {len(failed)}")
    for f in failed[:10]:
        print(f"  {f}")
    if failed:
        print(f"  (showing first 10 of {len(failed)})")


if __name__ == '__main__':
    users = sys.argv[1:] or ['DYJ', 'XYC']
    main(users)
