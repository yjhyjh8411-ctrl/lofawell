import os
import io
import uuid
import urllib.parse
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env

# import pandas as pd # Moved inside function
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, make_response
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)
CORS(app) # Enable CORS for all routes
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024 # 32MB Upload Limit
app.secret_key = 'lofa_infra_final_perfect_2026'
app.config['SESSION_COOKIE_NAME'] = '__session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True 
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

_db = None
_bucket = None
_firebase_initialized = False

def init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return

    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        if not firebase_admin._apps:
            if os.path.exists('serviceAccountKey.json'):
                cred = credentials.Certificate('serviceAccountKey.json')
                firebase_admin.initialize_app(cred, {
                    'storageBucket': 'lofa-43d38.firebasestorage.app',
                    'projectId': 'lofa-43d38'
                })
                print("Firebase initialized with serviceAccountKey.json")
            else:
                # Firebase App Hosting / Functions에서는 옵션 없이 호출하면 환경 변수(FIREBASE_CONFIG)를 통해 자동 설정됩니다.
                firebase_admin.initialize_app()
                print("Firebase initialized with Default Credentials")
        
        _firebase_initialized = True
        print("Firebase Cloud 연결 성공")
    except Exception as e:
        print(f"Firebase 연결 실패: {e}")

def get_db():
    global _db
    if _db is None:
        init_firebase()
        from firebase_admin import firestore
        _db = firestore.client()
    return _db

def get_bucket():
    global _bucket
    if _bucket is None:
        init_firebase()
        from firebase_admin import storage
        _bucket = storage.bucket()
    return _bucket

# --- [유틸리티 함수] ---
def upload_file_to_storage(file, user_id, user_name, apply_type):
    """Firebase Storage에 파일을 업로드하고 다운로드 URL을 반환합니다. 
    이미지 파일인 경우 자동으로 크기를 줄여서 업로드합니다."""
    if not file or file.filename == '':
        return ""
    
    try:
        now_date = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_name = secure_filename(file.filename)
        ext = os.path.splitext(original_name)[1].lower()
        filename = f"{user_id}_{user_name}_{apply_type or 'unknown'}_{now_date}_{original_name}"
        
        bucket = get_bucket()
        
        # 파일 읽기
        file_content = file.read()
        content_type = file.content_type or 'application/octet-stream'

        # 이미지 압축 처리 (JPG, JPEG, PNG, WEBP 등)
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            try:
                img = Image.open(io.BytesIO(file_content))
                
                # 이미지 모드 확인 및 변환 (RGBA -> RGB 등)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 이미지 크기 조정 (최대 너비/높이 1600px로 제한)
                max_size = 1600
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # 압축된 이미지를 메모리 버퍼에 저장
                img_io = io.BytesIO()
                img.save(img_io, format='JPEG', quality=80, optimize=True)
                file_content = img_io.getvalue()
                content_type = 'image/jpeg'
                
                # 확장자가 바뀌었으므로 파일명도 .jpg로 조정
                if not filename.lower().endswith('.jpg') and not filename.lower().endswith('.jpeg'):
                    filename = os.path.splitext(filename)[0] + '.jpg'
            except Exception as img_err:
                print(f"Image compression failed, using original: {img_err}")
        
        # Firebase Storage용 다운로드 토큰 생성 (가장 확실한 다운로드 방법)
        access_token = str(uuid.uuid4())
        
        blob = bucket.blob(f"uploads/{filename}")
        blob.metadata = {"firebaseStorageDownloadTokens": access_token}
        
        # 파일 업로드
        blob.upload_from_string(file_content, content_type=content_type)
        
        # 메타데이터 업데이트 (토큰 적용)
        blob.patch()
        
        # 브라우저에서 바로 다운로드되도록 Content-Disposition 설정 (선택 사항)
        # blob.content_disposition = f'attachment; filename="{original_name}"'
        # blob.patch()

        # Firebase Storage 표준 다운로드 URL 형식 생성
        encoded_name = urllib.parse.quote(f"uploads/{filename}", safe='')
        public_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{encoded_name}?alt=media&token={access_token}"
        
        return public_url
    except Exception as e:
        print(f"Upload Error: {e}")
        return ""

# --- [인증 체크 미들웨어] ---
@app.before_request
def enforce_login():
    # 로그인이 필요하지 않은 경로들
    allowed_endpoints = ['login_page', 'login_process', 'signup_page', 'signup_process', 'static', 'get_settings']
    
    # 세션에 user_id가 없고, 허용된 경로가 아닌 경우 로그인 페이지로 리다이렉트
    # 루트(/)도 리다이렉트 로직이 있으므로 예외 처리에 추가하거나 아래 route에서 처리
    if request.path == '/': return # 루트는 아래 index()에서 처리

    if request.endpoint not in allowed_endpoints and 'user_id' not in session:
        return redirect(url_for('login_page'))

# --- [보안 및 캐싱 방지 헤더 추가] ---
@app.after_request
def add_security_headers(response):
    # HTML 응답에 대해서만 캐싱을 강력하게 금지 (Cloudflare Edge Cache 방지)
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response

# --- [1. 로그인 및 세션] ---
@app.route('/')
def index():
    # 루트 접속 시 상태에 따라 분기 처리
    if 'user_id' in session and session.get('user_id'):
        return redirect(url_for('main_page'))
    return redirect(url_for('login_page'))

@app.route('/main')
def main_page():
    # 실제 메인 대시보드
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    uid = session['user_id']
    db = get_db()
    
    current_year = datetime.now().strftime('%Y')
    current_month = datetime.now().strftime('%Y-%m')
    
    # 💡 통합 한도 항목 및 개인별 월간 한도 설정
    shared_categories = ['주택지원', '의료비지원', '복지연금']
    individual_monthly_limit = 100000
    
    # 신규: 근로자가족문화활동비 반기 한도 (30만원)
    cultural_limit = 300000
    cultural_usage = 0
    current_month_int = int(datetime.now().strftime('%m'))
    current_half = 1 if current_month_int <= 6 else 2

    # 신규: 정기예방접종 연간 한도 (15만원)
    vaccine_limit = 150000
    vaccine_usage = 0

    total_shared_approved = 0
    # 카테고리별 이번 달 사용 금액 저장용
    category_monthly_usage = {}
    # 카테고리별 연간 사용 금액 저장용 (모든 항목 연동을 위해 추가)
    category_yearly_usage = {}
    
    try:
        # 💡 인덱스 오류 방지를 위해 쿼리를 단순화하고 메모리에서 세부 필터링합니다.
        docs = db.collection('applications') \
            .where('user_id', '==', str(uid)) \
            .where('status', '==', '승인') \
            .stream()
            
        for doc in docs:
            d = doc.to_dict()
            app_type = d.get('type', d.get('구분', ''))
            app_date = d.get('apply_date', d.get('신청일시', ''))
            amount = int(d.get('amount', d.get('신청금액', 0)))
            
            # 연도 필터링 (메모리)
            if app_date.startswith(current_year):
                # 모든 항목의 연간 합계 계산
                category_yearly_usage[app_type] = category_yearly_usage.get(app_type, 0) + amount

                if app_type in shared_categories:
                    total_shared_approved += amount
                
                # 정기예방접종 연간 합산
                if app_type == '정기예방접종':
                    vaccine_usage += amount

                # 월간 필터링 (메모리)
                if app_date.startswith(current_month):
                    category_monthly_usage[app_type] = category_monthly_usage.get(app_type, 0) + amount

                # 신규: 반기 필터링 (근로자가족문화활동비)
                if app_type == '근로자가족문화활동비':
                    try:
                        app_month = int(app_date.split('-')[1])
                        app_half = 1 if app_month <= 6 else 2
                        if app_half == current_half:
                            cultural_usage += amount
                    except:
                        pass
                
    except Exception as e:
        print(f"Usage calculation error: {e}")

    return render_template('main.html', 
                           user_name=session['user_name'],
                           used_amount=total_shared_approved,
                           total_limit=4800000,
                           monthly_usage=category_monthly_usage,
                           yearly_usage=category_yearly_usage,
                           monthly_limit=individual_monthly_limit,
                           cultural_usage=cultural_usage,
                           cultural_limit=cultural_limit,
                           current_half=current_half,
                           vaccine_usage=vaccine_usage,
                           vaccine_limit=vaccine_limit)

@app.route('/login', methods=['GET'])
def login_page():
    # 1. 이미 로그인되어 있다면 사번에 따라 분기 처리
    if 'user_id' in session and session.get('user_id'):
        if session.get('user_id') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('main_page'))
    
    # 2. URL 파라미터를 통한 자동 로그인 시도
    eid = request.args.get('employeeId')
    pw = request.args.get('password')
    error_msg = None
    
    if eid and pw:
        try:
            db = get_db()
            user_ref = db.collection('users').document(eid.strip()).get()
            if user_ref.exists:
                u_info = user_ref.to_dict()
                if str(u_info.get('비밀번호', '')).strip() == pw.strip():
                    session.permanent = True
                    session.update({
                        'user_id': eid.strip(),
                        'user_name': u_info['이름'],
                        'user_dept': u_info.get('부서', ''),
                        'user_rank': u_info.get('직급', ''),
                        'user_join_date': u_info.get('입사일', ''),
                        'user_phone': u_info.get('전화번호', '')
                    })
                    if eid.strip() == 'admin':
                        return redirect(url_for('admin_dashboard'))
                    return redirect(url_for('main_page'))
                else:
                    error_msg = "비밀번호가 일치하지 않습니다."
            else:
                error_msg = "등록되지 않은 사번입니다."
        except Exception as e:
            print(f"Auto-login error: {e}")
            error_msg = "자동 로그인 중 오류가 발생했습니다."
        
    # 3. 파라미터가 없거나 인증 실패 시 로그인 템플릿 반환
    resp = make_response(render_template('login.html', error_msg=error_msg))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

@app.route('/login_process', methods=['POST'])
def login_process():
    try:
        sid = str(request.form['employeeId']).strip()
        pw = str(request.form['password']).strip()
        
        db = get_db()
        user_ref = db.collection('users').document(sid).get()
        
        if user_ref.exists:
            u_info = user_ref.to_dict()
            stored_pw = str(u_info.get('비밀번호', '')).strip()
            
            if stored_pw == pw:
                session.permanent = True
                session.update({
                    'user_id': sid,
                    'user_name': u_info['이름'],
                    'user_dept': u_info.get('부서', ''),
                    'user_rank': u_info.get('직급', ''),
                    'user_join_date': u_info.get('입사일', ''),
                    'user_phone': u_info.get('전화번호', '')
                })
                return jsonify({"status": "success", "is_admin": sid == "admin"})
            else:
                return jsonify({"status": "error", "message": "비밀번호가 일치하지 않습니다."})
        
        return jsonify({"status": "error", "message": "등록되지 않은 사번입니다. 회원가입을 먼저 진행해 주세요."})
    except Exception as e:
        print(f"Login Error: {e}")
        return jsonify({"status": "error", "message": f"로그인 중 오류: {e}"})

# --- [2. 신청서 페이지 로드] ---
@app.route('/apply/<page>')
def apply_page(page):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    edit_app_id = request.args.get('edit_app_id')
    data, edit_mode = None, False

    if edit_app_id:
        db = get_db()
        doc = db.collection('applications').document(edit_app_id).get()
        if doc.exists:
            data = doc.to_dict()
            # 템플릿에서 기존 값을 input의 name값으로 바로 참조할 수 있도록 raw_data 병합
            if 'raw_data' in data:
                raw = data.get('raw_data', {})
                for k, v in raw.items():
                    if k not in data:
                        data[k] = v
            edit_mode = True

    if not data:
        data = {
            '사번': session.get('user_id'),
            '성명': session.get('user_name'),
            '부서': session.get('user_dept'),
            '직급': session.get('user_rank'),
            '입사일': session.get('user_join_date'),
            '전화번호': session.get('user_phone', '')
        }

    return render_template(f'{page}.html', 
                           user_name=session['user_name'], 
                           user_id=session.get('user_id'),
                           user_dept=session.get('user_dept'),
                           edit_mode=edit_mode, 
                           data=data)

# --- [3. 신청서 제출] ---
@app.route('/submit', methods=['GET', 'POST'])
@app.route('/edit_submit', methods=['POST'])
def handle_submit():
    print(f"Submit Request: {request.method} {request.path}")
    
    if request.method == 'GET':
        return jsonify({"status": "ok", "message": "Submit endpoint is reachable."})

    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "세션 만료. 다시 로그인해주세요."}), 401
    
    try:
        user_id = str(session.get('user_id'))
        user_name = str(session.get('user_name'))
        apply_type = request.form.get('type', '일반신청')
        app_id = request.form.get('app_id')
        
        amount_raw = str(request.form.get('amount', '0')).replace(',', '')
        try:
            amount_val = int(float(amount_raw))
        except (ValueError, TypeError):
            amount_val = 0

        # 개인정보 수집 및 이용 동의 체크
        if request.form.get('privacy_consent') != 'on':
            return jsonify({"status": "error", "message": "개인정보 수집 및 이용에 동의해야 신청이 가능합니다."}), 400

        db = get_db()

        # 중복 제출 방지 (신규 신청인 경우만 체크)
        if not app_id or app_id == 'None':
            five_mins_ago = (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
            
            # 인덱스 오류 방지를 위해 equality 필터만 사용하고, 날짜는 메모리에서 체크
            recent_apps_query = db.collection('applications') \
                .where('user_id', '==', user_id) \
                .where('type', '==', apply_type) \
                .where('amount', '==', amount_val) \
                .limit(5).get()
            
            is_duplicate = False
            for doc in recent_apps_query:
                d = doc.to_dict()
                app_time = d.get('apply_date', d.get('신청일시', ''))
                if app_time >= five_mins_ago:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                return jsonify({
                    "status": "error", 
                    "message": "방금 동일한 내용의 신청서가 제출되었습니다. 중복 제출을 방지하기 위해 5분 후 다시 시도해 주세요."
                }), 400

        print(f"Form Data: {request.form}")
        print(f"Files: {request.files}")

        file = request.files.get('attachment')
        file_url = request.form.get('old_filename', '')
        
        if file and file.filename != '':
            file_url = upload_file_to_storage(file, user_id, user_name, apply_type)

        # 모든 폼 데이터를 딕셔너리로 수집
        form_data_all = {}
        for key in request.form.keys():
            if key not in ['app_id', 'old_filename', 'type']:
                form_data_all[key] = request.form.get(key)
        
        detail_parts = [
            f"항목:{request.form.get('item_name', '')}",
            f"금융:{request.form.get('bank_name', '')}",
            f"본인부담:{request.form.get('self_pay', '0')}",
            f"지원구분:{request.form.get('target_name', '')}",
            f"내용:{request.form.get('detail_text', '')}"
        ]
        clean_detail = " / ".join(p for p in detail_parts if not p.endswith(':') and not p.endswith(':0'))
        if not clean_detail:
            clean_detail = request.form.get('detail_text', '')

        if not app_id or app_id == 'None':
            app_id = str(int(datetime.now().timestamp() * 1000))
            msg = "신청이 완료되었습니다."
        else:
            msg = "수정이 완료되었습니다."

        new_data = {
            'app_id': app_id,
            'apply_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type': apply_type,
            'user_dept': request.form.get('user_dept'),
            'user_id': user_id,
            'user_rank': request.form.get('position'),
            'user_name': user_name,
            'join_date': request.form.get('joinDate', ''),
            'phone': request.form.get('phone', ''),
            'amount': amount_val,
            'account': request.form.get('account', ''),
            'detail': clean_detail,
            'status': '대기', # 수정 시에도 다시 대기 상태로 변경
            'reject_reason': '',
            'target_name': request.form.get('target_name', ''),
            'attachment': file_url,
            'raw_data': form_data_all,  # 모든 원본 필드 저장
            # 하위 호환성을 위해 한글 필드도 유지
            '사번': user_id,
            '성명': user_name,
            '부서': request.form.get('user_dept'),
            '직급': request.form.get('position'),
            '입사일': request.form.get('joinDate', ''),
            '전화번호': request.form.get('phone', ''),
            '구분': apply_type,
            '신청일시': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '신청금액': amount_val,
            '계좌번호': request.form.get('account', ''),
            '세부내용': clean_detail,
            '상태': '대기',
            '대상자성명': request.form.get('target_name', ''),
            '첨부파일': file_url,
            '반려의견': ''
        }

        db.collection('applications').document(app_id).set(new_data)
        
        return jsonify({"status": "success", "message": msg})

    except Exception as e:
        print(f"Submit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- [4. 현황 및 관리자 페이지] ---
@app.route('/my_status')
def my_status():
    if 'user_id' not in session: return redirect(url_for('index'))

    uid = str(session.get('user_id'))
    current_year = datetime.now().year
    selected_year = request.args.get('year', str(current_year))
    years = [str(y) for y in range(current_year, current_year - 4, -1)]

    print(f"DEBUG: Status query for user_id: {uid}, year: {selected_year}")

    try:
        db = get_db()
        # ASCII 필드명을 사용하여 쿼리
        docs = db.collection('applications').where('user_id', '==', uid).stream()

        applications = []
        for doc in docs:
            d = doc.to_dict()
            # 하위 호환성을 위한 데이터 매핑
            if '신청일시' not in d and 'apply_date' in d: d['신청일시'] = d['apply_date']
            if '구분' not in d and 'type' in d: d['구분'] = d['type']
            if '상태' not in d and 'status' in d: d['상태'] = d['status']
            if '신청금액' not in d and 'amount' in d: d['신청금액'] = d['amount']
            if '반려의견' not in d and 'reject_reason' in d: d['반려의견'] = d['reject_reason']

            # 연도 필터링
            app_date = d.get('신청일시', d.get('apply_date', ''))
            if app_date.startswith(selected_year):
                applications.append(d)

        applications.sort(key=lambda x: x.get('apply_date', x.get('신청일시', '')), reverse=True)
        return render_template('my_status.html', user_name=session['user_name'], applications=applications, years=years, selected_year=selected_year)

    except Exception as e:
        print(f"DEBUG: Status query fatal error: {e}")
        # Fallback: Fetch all and filter in memory if necessary
        try:
            all_docs = db.collection('applications').stream()
            applications = []
            for doc in all_docs:
                d = doc.to_dict()
                if str(d.get('user_id')) == uid or str(d.get('사번')) == uid:
                    if '신청일시' not in d and 'apply_date' in d: d['신청일시'] = d['apply_date']
                    if '반려의견' not in d and 'reject_reason' in d: d['반려의견'] = d['reject_reason']
                    app_date = d.get('신청일시', d.get('apply_date', ''))
                    if app_date.startswith(selected_year):
                        applications.append(d)
            applications.sort(key=lambda x: x.get('apply_date', x.get('신청일시', '')), reverse=True)
            return render_template('my_status.html', user_name=session['user_name'], applications=applications, years=years, selected_year=selected_year)
        except Exception as e2:
            return jsonify({"status": "error", "message": f"데이터 로드 실패: {e}"}), 500

@app.route('/cancel_apply', methods=['POST'])
def cancel_apply():
    if 'user_id' not in session: return jsonify({"status": "error", "message": "세션 만료"}), 401
    
    app_id = request.form.get('app_id')
    action = request.form.get('action') # 'cancel' or 'delete'
    
    try:
        db = get_db()
        doc_ref = db.collection('applications').document(app_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({"status": "error", "message": "해당 내역을 찾을 수 없습니다."})
        
        data = doc.to_dict()
        if str(data.get('사번')) != str(session.get('user_id')):
            return jsonify({"status": "error", "message": "권한이 없습니다."})
            
        if action == 'delete':
            doc_ref.delete()
            return jsonify({"status": "success", "message": "삭제되었습니다."})
        else:
            doc_ref.update({'상태': '취소'})
            return jsonify({"status": "success", "message": "취소되었습니다."})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin')
def admin_dashboard():
    if session.get('user_id') != 'admin': return redirect(url_for('index'))
    
    # 신청서 순서: 주택지원, 복지연금, 의료비지원, 생활복지지원, 문화활동비, 대부신청, 경조비지원, 정기예방접종, 장학금지원, 다자녀가정지원, 선진산업시찰, 모성보호지원, 위로금지원
    cats = ['주택지원', '복지연금', '의료비지원', '생활복지지원', '근로자가족문화활동비', '대부신청', '경조비지원', '정기예방접종', '장학금지원', '다자녀가정지원', '선진산업시찰', '모성보호지원', '위로금지원']
    
    db = get_db()
    docs = db.collection('applications').stream()
    all_apps = []
    for doc in docs:
        d = doc.to_dict()
        # 하위 호환성을 위한 데이터 매핑
        if '신청일시' not in d and 'apply_date' in d: d['신청일시'] = d['apply_date']
        if '구분' not in d and 'type' in d: d['구분'] = d['type']
        if '상태' not in d and 'status' in d: d['상태'] = d['status']
        if '신청금액' not in d and 'amount' in d: d['신청금액'] = d['amount']
        if '사번' not in d and 'user_id' in d: d['사번'] = d['user_id']
        if '성명' not in d and 'user_name' in d: d['성명'] = d['user_name']
        if '부서' not in d and 'user_dept' in d: d['부서'] = d['user_dept']
        if '직급' not in d and 'user_rank' in d: d['직급'] = d['user_rank']
        if '입사일' not in d and 'join_date' in d: d['입사일'] = d['join_date']
        if '첨부파일' not in d and 'attachment' in d: d['첨부파일'] = d['attachment']
        all_apps.append(d)
    
    # 최신순 정렬
    all_apps.sort(key=lambda x: x.get('신청일시', ''), reverse=True)
    
    summary = {}
    stats = {'total': len(all_apps), 'wait': 0, 'approve': 0, 'reject': 0}
    pending_list = []
    
    for app_item in all_apps:
        status = app_item.get('상태')
        if status == '대기': 
            stats['wait'] += 1
            pending_list.append(app_item)
        elif status == '승인': stats['approve'] += 1
        elif status == '반려': stats['reject'] += 1
        
        user_key = (app_item.get('사번'), app_item.get('성명'))
        if user_key not in summary:
            summary[user_key] = {cat: [] for cat in cats}
            summary[user_key]['사번'] = app_item.get('사번')
            summary[user_key]['성명'] = app_item.get('성명')
            summary[user_key]['부서'] = app_item.get('부서', '-')
            summary[user_key]['직급'] = app_item.get('직급', '-')
            summary[user_key]['입사일'] = app_item.get('입사일', '-')
            summary[user_key]['전화번호'] = app_item.get('전화번호', '-')
        
        cat = app_item.get('구분')
        if cat in cats:
            summary[user_key][cat].append({
                'app_id': app_item['app_id'],
                'amount': format(app_item.get('신청금액', 0), ','),
                'status': status,
                'apply_date': app_item['신청일시'],
                'attachment': app_item.get('첨부파일', ''), # summary에 명시적 포함
                'detail': app_item
            })

    return render_template('admin.html', 
                           summary=list(summary.values()), 
                           categories=cats, 
                           stats=stats, 
                           pending_list=pending_list,
                           user_name=session['user_name'])

def send_notification_email(to_email, subject, body):
    """지정된 이메일로 알림 메일을 발송합니다."""
    # 💡 보안을 위해 Google 계정의 [앱 비밀번호] 사용을 강력히 권장합니다.
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = os.environ.get('SENDER_EMAIL', 'lofawellfare@gmail.com')
    sender_password = os.environ.get('SENDER_PASSWORD', 'your-app-password')

    if not to_email or sender_email == 'your-email@gmail.com' or sender_password == 'your-app-password':
        print(f"Email skip: to={to_email}, sender={sender_email} (설정 확인 필요)")
        return False

    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender_email
        msg['To'] = to_email

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

@app.route('/admin_process', methods=['POST'])
def admin_process():
    if session.get('user_id') != 'admin': return jsonify({"status": "error"})
    
    app_id = request.form.get('app_id')
    status = request.form.get('status')
    reason = request.form.get('reason', '')
    
    db = get_db()
    
    # 1. 신청서 업데이트
    doc_ref = db.collection('applications').document(app_id)
    doc = doc_ref.get()
    if not doc.exists:
        return jsonify({"status": "error", "message": "신청서를 찾을 수 없습니다."})
    
    app_data = doc.to_dict()
    user_id = app_data.get('user_id', app_data.get('사번'))
    app_type = app_data.get('type', app_data.get('구분', '복지신청'))

    doc_ref.update({
        'status': status,
        '상태': status,
        'reject_reason': reason,
        '반려의견': reason
    })

    # 2. 사용자 정보에서 이메일 가져오기 및 알림 발송
    try:
        user_doc = db.collection('users').document(str(user_id)).get()
        if user_doc.exists:
            u_info = user_doc.to_dict()
            user_email = u_info.get('이메일', u_info.get('email'))
            user_name = u_info.get('이름', '임직원')

            if user_email:
                subject = f"[LOFA 복지기금] {app_type} 신청 건이 {status}되었습니다."
                body = f"안녕하세요, {user_name}님.\n\n"
                body += f"요청하신 '{app_type}' 신청 결과가 [{status}] 처리되었습니다.\n"
                if status == '반려' and reason:
                    body += f"\n[반려 사유]\n{reason}\n"
                    body += "\n내 정보 > 신청 현황 메뉴에서 내용을 수정하여 재신청하실 수 있습니다.\n"
                
                body += "\n감사합니다.\nLOFA 사내근로복지기금 시스템"
                
                send_notification_email(user_email, subject, body)
    except Exception as e:
        print(f"Notification error: {e}")

    return jsonify({"status": "success"})

# --- [직원 정보 관리 API] ---
@app.route('/api/users')
def api_users():
    if session.get('user_id') != 'admin':
        return jsonify({"status": "error"}), 403
    db = get_db()
    users = []
    for doc in db.collection('users').stream():
        u = doc.to_dict()
        u.pop('비밀번호', None)  # 비밀번호는 노출하지 않음
        users.append(u)
    users.sort(key=lambda x: x.get('사번', ''))
    return jsonify({"status": "success", "users": users})

@app.route('/admin/user/update', methods=['POST'])
def admin_user_update():
    if session.get('user_id') != 'admin':
        return jsonify({"status": "error"}), 403
    user_id = request.form.get('user_id', '').strip()
    if not user_id:
        return jsonify({"status": "error", "message": "사번이 필요합니다."})
    db = get_db()
    update_data = {}
    for field in ['이름', '직급', '부서', '이메일', '입사일', '전화번호']:
        val = request.form.get(field)
        if val is not None:
            update_data[field] = val.strip()
    new_pw = request.form.get('새비밀번호', '').strip()
    if new_pw:
        update_data['비밀번호'] = new_pw
    db.collection('users').document(user_id).update(update_data)
    return jsonify({"status": "success"})

@app.route('/admin/user/delete', methods=['POST'])
def admin_user_delete():
    if session.get('user_id') != 'admin':
        return jsonify({"status": "error"}), 403
    user_id = request.form.get('user_id', '').strip()
    if not user_id:
        return jsonify({"status": "error", "message": "사번이 필요합니다."})
    db = get_db()
    db.collection('users').document(user_id).delete()
    return jsonify({"status": "success"})

# --- [엑셀 다운로드 기능 개선] ---
@app.route('/download_excel')
def download_excel():
    if session.get('user_id') != 'admin': return redirect(url_for('index'))
    
    try:
        import pandas as pd
        db = get_db()
        docs = db.collection('applications').stream()
        all_apps = []
        for doc in docs:
            d = doc.to_dict()
            # 하위 호환성을 위한 데이터 매핑
            if '신청일시' not in d and 'apply_date' in d: d['신청일시'] = d['apply_date']
            if '구분' not in d and 'type' in d: d['구분'] = d['type']
            if '상태' not in d and 'status' in d: d['상태'] = d['status']
            if '신청금액' not in d and 'amount' in d: d['신청금액'] = d['amount']
            if '사번' not in d and 'user_id' in d: d['사번'] = d['user_id']
            if '성명' not in d and 'user_name' in d: d['성명'] = d['user_name']
            if '부서' not in d and 'user_dept' in d: d['부서'] = d['user_dept']
            if '직급' not in d and 'user_rank' in d: d['직급'] = d['user_rank']
            if '입사일' not in d and 'join_date' in d: d['입사일'] = d['join_date']
            if '첨부파일' not in d and 'attachment' in d: d['첨부파일'] = d['attachment']
            if '반려의견' not in d and 'reject_reason' in d: d['반려의견'] = d['reject_reason']

            # 원본 데이터(raw_data)가 있으면 그것을 기반으로 정리
            row = {
                'ID': d.get('app_id'),
                '신청일시': d.get('신청일시'),
                '구분': d.get('구분'),
                '사번': d.get('사번'),
                '성명': d.get('성명'),
                '부서': d.get('부서'),
                '직급': d.get('직급'),
                '입사일': d.get('입사일'),
                '전화번호': d.get('전화번호'),
                '신청금액': d.get('신청금액'),
                '계좌번호': d.get('계좌번호'),
                '상태': d.get('상태'),
                '반려의견': d.get('반려의견'),
                '첨부파일': d.get('첨부파일')
            }
            # raw_data에 있는 추가 필드들도 병합 (중복 제외)
            if 'raw_data' in d and isinstance(d['raw_data'], dict):
                for k, v in d['raw_data'].items():
                    if k not in ['user_name', 'user_id', 'user_dept', 'position', 'joinDate', 'phone', 'amount', 'account', 'type']:
                        row[f"상세_{k}"] = v
            all_apps.append(row)
        
        if not all_apps:
            return "데이터가 없습니다."

        df = pd.DataFrame(all_apps)
        
        # 컬럼 순서 조정 (주요 정보 우선)
        main_cols = ['사번', '성명', '구분', '신청금액', '상태', '신청일시', '부서', '직급', '입사일', '전화번호', '계좌번호']
        cols = [c for c in main_cols if c in df.columns] + [c for c in df.columns if c not in main_cols]
        df = df[cols]
        
        # 엑셀 파일 생성 (메모리상에서)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='복지신청내역')
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=f"LOFA_applications_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return f"엑셀 다운로드 오류: {e}"

# --- [5. 회원가입 및 로그아웃] ---
@app.route('/signup_process', methods=['POST'])
def signup_process():
    # 개인정보 수집 및 이용 동의 체크
    if request.form.get('privacy_consent') != 'on':
        return jsonify({"status": "error", "message": "개인정보 수집 및 이용에 동의해야 가입이 가능합니다."}), 400

    sid = str(request.form.get('employeeId')).strip()
    pw = str(request.form.get('password')).strip()
    
    db = get_db()
    user_ref = db.collection('users').document(sid).get()
    
    if user_ref.exists:
        return jsonify({"status": "error", "message": "이미 등록된 사번입니다."})
    
    new_user = {
        '사번': sid,
        '비밀번호': pw,
        '이름': request.form.get('userName'),
        '직급': request.form.get('position'),
        '부서': request.form.get('department'),
        '이메일': request.form.get('email'),
        '입사일': request.form.get('joinDate'),
        '전화번호': request.form.get('phone')
    }
    db.collection('users').document(sid).set(new_user)
    return jsonify({"status": "success"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

# --- [6. 사이트 설정 (규정집 버전관리, 공지사항)] ---
@app.route('/api/settings', methods=['GET'])
def get_settings():
    try:
        db = get_db()
        # 공지사항 가져오기
        site_doc = db.collection('settings').document('site_content').get()
        site_data = site_doc.to_dict() if site_doc.exists else {}
        
        # 최신 규정집 버전 가져오기
        latest_rules = {}
        versions_ref = db.collection('settings').document('site_content').collection('rule_versions')
        versions = versions_ref.order_by('created_at', direction='DESCENDING').limit(1).get()
        if versions:
            latest_rules = versions[0].to_dict()
        
        # 모든 버전 목록 (관리용)
        all_versions = []
        all_v_docs = versions_ref.order_by('created_at', direction='DESCENDING').limit(20).get()
        for v in all_v_docs:
            all_versions.append(v.to_dict())

        return jsonify({
            "notice": site_data.get('notice', '공지사항이 없습니다.'),
            "latest_rules": latest_rules,
            "all_versions": all_versions
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin/settings/update', methods=['POST'])
def update_settings():
    if session.get('user_id') != 'admin': return jsonify({"status": "error", "message": "권한이 없습니다."}), 403
    
    try:
        db = get_db()
        mode = request.form.get('mode') # 'notice' or 'rules_version'
        
        if mode == 'notice':
            notice = request.form.get('notice', '')
            db.collection('settings').document('site_content').set({
                "notice": notice,
                "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }, merge=True)
            return jsonify({"status": "success", "message": "공지사항이 저장되었습니다."})
            
        elif mode == 'rules_version':
            v_name = request.form.get('version_name', 'v1.0')
            content = request.form.get('rules', '')
            files = request.files.getlist('rules_files')
            
            uploaded_files = []
            for f in files:
                if f and f.filename != '':
                    f_url = upload_file_to_storage(f, "admin", "system", f"rules_{v_name}")
                    uploaded_files.append({"name": f.filename, "url": f_url})
            
            v_id = str(int(datetime.now().timestamp()))
            db.collection('settings').document('site_content').collection('rule_versions').document(v_id).set({
                "version_id": v_id,
                "version_name": v_name,
                "content": content,
                "files": uploaded_files,
                "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            return jsonify({"status": "success", "message": f"새 버전({v_name})이 등록되었습니다."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin/rules_version/delete', methods=['POST'])
def delete_rules_version():
    if session.get('user_id') != 'admin':
        return jsonify({"status": "error", "message": "권한이 없습니다."}), 403
    version_id = request.form.get('version_id', '').strip()
    if not version_id:
        return jsonify({"status": "error", "message": "version_id가 필요합니다."})
    try:
        db = get_db()
        db.collection('settings').document('site_content').collection('rule_versions').document(version_id).delete()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    init_firebase()
    app.run(host='0.0.0.0', port=5000, debug=True)
