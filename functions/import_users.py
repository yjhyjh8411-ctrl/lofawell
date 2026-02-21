import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import os

# Firebase 설정
os.environ['GCLOUD_PROJECT'] = 'lofa-43d38'

if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()

def import_users():
    try:
        # 엑셀 파일 읽기
        df = pd.read_excel('users.xlsx')
        print(f"엑셀 파일 로드 성공: 총 {len(df)}명의 사용자")

        for _, row in df.iterrows():
            # '사번'을 문서 ID로 사용
            sid = str(row['사번']).strip()
            # 데이터 정제 (NaN 처리 등)
            user_data = row.to_dict()
            # NaN 값은 Firestore에 저장할 수 없으므로 빈 문자열로 변환
            clean_data = {k: (v if pd.notna(v) else "") for k, v in user_data.items()}
            
            # Firestore에 저장
            db.collection('users').document(sid).set(clean_data)
            print(f"사용자 업로드 완료: {sid} ({clean_data.get('이름', '')})")
            
        print("모든 사용자 데이터 업로드가 완료되었습니다.")
    except Exception as e:
        print(f"업로드 중 오류 발생: {e}")

if __name__ == "__main__":
    import_users()
