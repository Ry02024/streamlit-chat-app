import streamlit as st
import firebase_admin
from firebase_admin import credentials, auth, firestore # firestore をインポート
import os
import json
import datetime # datetime をインポート
import pytz     # pytz をインポート
# !!! joedged/streamlit-firebase-auth のインポート !!!
from streamlit_firebase_auth import FirebaseAuth

# --- ページ設定 (一番最初に呼び出す) ---
st.set_page_config(
    page_title="Secure Chat App",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ★★★ 許可ユーザーリストの読み込み (環境変数から) ★★★ ---
ALLOWED_USERS = [] # デフォルトは空
try:
    # 環境変数からカンマ区切り文字列として読み込む想定
    allowed_users_str = os.environ.get("ALLOWED_USERS_STR", "")
    if allowed_users_str:
        ALLOWED_USERS = [email.strip() for email in allowed_users_str.split(',') if email.strip()]
        print("DEBUG: Allowed users loaded from env var.")
    else:
        # 環境変数が設定されていない場合の警告
        st.warning("許可ユーザーリスト (ALLOWED_USERS_STR env var) が設定されていません。")
except Exception as e:
    st.error(f"許可ユーザーリストの読み込み/パースに失敗: {e}")
    ALLOWED_USERS = [] # エラー時は誰も入れない

# --- Firebase Admin SDK 初期化 ---
if not firebase_admin._apps:
    try:
        # 環境変数またはデフォルト認証情報を使用
        if 'FIREBASE_CREDENTIALS_JSON' in os.environ:
            cred_json_str = os.environ.get("FIREBASE_CREDENTIALS_JSON")
            if cred_json_str:
                 cred_dict = json.loads(cred_json_str)
                 cred = credentials.Certificate(cred_dict)
                 firebase_admin.initialize_app(cred)
                 print("DEBUG: Admin SDK Initialized from env var.")
            else:
                 st.error("CRITICAL ERROR: Env var FIREBASE_CREDENTIALS_JSON is empty.")
                 st.stop()
        else:
             firebase_admin.initialize_app()
             print("DEBUG: Admin SDK Initialized with default credentials.")
    except ValueError as e:
         if "The default Firebase app already exists" not in str(e):
              st.error(f"CRITICAL ERROR: Firebase Admin SDK Init ValueError: {e}")
              st.stop()
    except Exception as e:
        st.error(f"CRITICAL ERROR: Firebase Admin SDK Init Failed: {e}")
        st.stop()


# --- Firebase Webアプリ設定の読み込み (環境変数から) ---
firebase_config = None
try:
    web_config_json = os.environ.get("FIREBASE_WEB_CONFIG_JSON")
    if web_config_json:
        firebase_config = json.loads(web_config_json)
        print("DEBUG: Web Config Loaded from env var.")
    else:
        st.error("CRITICAL ERROR: FIREBASE_WEB_CONFIG_JSON environment variable not set.")
        st.stop()
except Exception as e:
    st.error(f"CRITICAL ERROR: Web Config Load Failed: {e}")
    st.stop()

# --- Firestore クライアント初期化 ---
# (変更なし)
db = None
try:
    db = firestore.client()
except Exception as e:
    st.error(f"CRITICAL ERROR: Firestore Client Initialization Failed: {e}")
    st.stop()

# --- Streamlit UI メイン部分 ---
st.title("Chat App with Google Login")

# --- 認証ライブラリのインスタンス化 ---
auth_obj = None
try:
    auth_obj = FirebaseAuth(firebase_config)
except Exception as e:
    st.error(f"CRITICAL ERROR: FirebaseAuth Instantiation Failed: {e}")
    st.stop()

# --- ログイン状態の管理と処理 ---
if 'user_info' not in st.session_state: st.session_state.user_info = None
if 'login_error' not in st.session_state: st.session_state.login_error = None
if 'is_authorized' not in st.session_state: st.session_state.is_authorized = False

user_info_from_library = None
temp_login_success = False
temp_user_email = None
temp_user_data = None
login_form_placeholder = st.empty()

# --- 表示の切り替え ---
if st.session_state.get('user_info') and st.session_state.get('is_authorized'):
    # === ログイン済み・認可済みの場合 ===
    user_data = st.session_state.user_info
    my_uid = None
    my_email = None
    my_name = "User"
    user_details = None

    # --- ユーザー情報取得 & Firestore保存 ---
    if isinstance(user_data, dict) and user_data.get('success') and 'user' in user_data:
        user_details = user_data['user']
        my_uid = user_details.get('uid')
        if not my_uid: my_uid = user_details.get('localId')
        my_email = user_details.get('email')
        my_name = user_details.get('displayName', my_email if my_email else "User")

        # Firestoreへの保存処理
        if my_uid and my_email and user_details:
            user_doc_ref = db.collection('users').document(my_uid)
            try:
                user_doc_ref.set({
                    'uid': my_uid, 'email': my_email, 'displayName': my_name,
                    'lastLogin': firestore.SERVER_TIMESTAMP
                }, merge=True)
            except Exception as e:
                st.warning(f"ユーザー情報の保存/更新失敗: {e}")

    # --- サイドバー表示 ---
    with st.sidebar:
        st.success("ログイン中")
        st.write("ユーザー情報:")
        if my_name: st.write(f"Name: {my_name}")
        if my_email: st.write(f"Email: {my_email}")
        if my_uid: st.write(f"UID: {my_uid}")
        else: st.error("!!! UIDが見つかりません !!!")

        # ログアウトフォーム表示
        try:
             logout_placeholder = st.empty()
             with logout_placeholder:
                 logout_clicked = auth_obj.logout_form()
                 # ログアウト後の処理は下のelseブロックで handle
        except Exception as e:
            st.error(f"Logout failed: {e}")

    # --- メイン画面 (チャットUI) ---
    if not my_uid:
        st.error("ユーザーIDが取得できませんでした。")
    else:
        st.header("Chat Room")

        # --- ヘルパー関数定義 ---
        # ★★★ 関数に current_user_uid 引数を追加 ★★★
        # ★★★ キャッシュキーがユーザーごとに異なるように変更 ★★★
        @st.cache_data(ttl=300)
        def get_user_list(current_user_uid):
             print(f"--- DEBUG: get_user_list called for UID: {current_user_uid} ---") # どのユーザーで呼ばれたか確認
             users = []
             try:
                 users_ref = db.collection('users').stream()
                 count = 0
                 for user_doc in users_ref:
                     count += 1
                     user_data_from_db = user_doc.to_dict()
                     # ★★★ 引数で渡された current_user_uid でフィルタリング ★★★
                     if user_data_from_db.get('uid') != current_user_uid and user_data_from_db.get('email'):
                         print(f"--- DEBUG: Appending user: {user_data_from_db.get('email')}")
                         users.append(user_data_from_db)
                     # else:
                     #     print(f"--- DEBUG: Skipping user: {user_data_from_db.get('email')} (Self or no email)")
                 # print(f"--- DEBUG: Finished reading stream. Total docs read: {count} ---")
             except Exception as e:
                 st.warning(f"ユーザーリスト取得失敗: {e}.")
                 print(f"--- DEBUG: Exception during user list fetch: {e} ---")

             unique_users = {user.get('email', ''): user for user in users if user.get('email')}.values()
             print(f"--- DEBUG: Returning unique users count for {current_user_uid}: {len(unique_users)} ---")
             return list(unique_users)

        def display_messages(room_id, message_area):
             # ... (変更なし) ...
             try:
                 messages_ref = db.collection("chat_rooms").document(room_id).collection("messages").order_by("timestamp", direction=firestore.Query.ASCENDING).limit(100)
                 messages = messages_ref.stream()
                 with message_area:
                     #st.empty()
                     for msg_doc in messages:
                         msg = msg_doc.to_dict()
                         sender_name_disp = msg.get('sender_name', 'Unknown')
                         timestamp = msg.get('timestamp')
                         timestamp_jp = "N/A"
                         if timestamp and hasattr(timestamp, 'astimezone'):
                             try:
                                 timestamp_jp = timestamp.astimezone(pytz.timezone('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S')
                             except ValueError:
                                 timestamp_jp = timestamp.strftime('%Y-%m-%d %H:%M:%S') + " (UTC?)"

                         is_user = msg.get('sender_uid') == my_uid # ここは現在のユーザー(my_uid)でOK
                         with st.chat_message(name="user" if is_user else sender_name_disp):
                             st.markdown(f"{msg.get('content', '')}")
                             st.caption(f"{sender_name_disp} - {timestamp_jp}")
             except Exception as e:
                  st.error(f"メッセージの読み込みに失敗しました: {e}")

        def send_message(room_id, partner_uid, content):
             # ... (変更なし) ...
             if content and my_uid and partner_uid:
                 try:
                     doc_ref = db.collection("chat_rooms").document(room_id).collection("messages").document()
                     doc_ref.set({
                         'sender_uid': my_uid,
                         'sender_name': my_name,
                         'receiver_uid': partner_uid,
                         'content': content,
                         'timestamp': datetime.datetime.now(pytz.utc)
                     })
                 except Exception as e:
                      st.error(f"メッセージの送信に失敗しました: {e}")

        # --- チャット相手選択 (表示名をリストにする) ---
        # ★★★ get_user_list に現在の my_uid を渡す ★★★
        available_partners_data = get_user_list(my_uid)

        if available_partners_data:
            # 表示名とEmailのマッピング
            partner_display_options = {
                user.get('displayName', user.get('email', 'Unknown')): user.get('email')
                for user in available_partners_data
                if user.get('email')
            }
            display_name_list = [""] + list(partner_display_options.keys())

            # selectbox で表示名を選択
            selected_display_name = st.selectbox(
                "Select Chat Partner:",
                options=display_name_list,
                key="partner_select",
                index=0,
            )
        else:
             st.info("チャット可能な相手がいません。他の許可ユーザーがログインし、情報がFirestoreに保存されると表示されます。")
             selected_display_name = None

        # --- チャット表示と入力 ---
        if selected_display_name:
            selected_partner_email = partner_display_options.get(selected_display_name)
            if selected_partner_email:
                selected_partner_data = next((user for user in available_partners_data if user.get('email') == selected_partner_email), None)
                if selected_partner_data:
                    partner_uid = selected_partner_data.get('uid')
                    partner_name = selected_partner_data.get('displayName', selected_partner_email)

                    if not partner_uid:
                        st.error("選択した相手のUIDが見つかりません。")
                    else:
                        room_id = "_".join(sorted([my_uid, partner_uid]))
                        st.subheader(f"Chat with: {partner_name} ({selected_partner_email})")
                        message_area = st.container()
                        message_area.height = 400
                        display_messages(room_id, message_area)
                        if prompt := st.chat_input("メッセージを入力"):
                            send_message(room_id, partner_uid, prompt)
                            # st.rerun() # リアルタイム更新用（注意点あり）
                else:
                     st.error("選択されたパートナーの情報が見つかりませんでした。")
            else:
                st.error("選択された表示名に対応するEmailが見つかりませんでした。")
        elif available_partners_data: # 選択肢はあるがまだ選んでいない場合
            st.info("チャット相手を選択してください。")

# --- 未ログイン時または未認可時の表示 ---
else:
    # ログインフォームを表示させるためのプレースホルダー
    with login_form_placeholder:
        try:
            # まずログインフォームを表示し、結果を受け取る
            user_info_from_library = auth_obj.login_form()

            # login_form が情報を返した場合 (ログイン試行があった場合)
            if user_info_from_library:
                temp_login_success = True
                temp_user_data = user_info_from_library
                temp_user_email = None

                # Emailを取得
                if isinstance(temp_user_data, dict) and temp_user_data.get('success') and 'user' in temp_user_data:
                    temp_user_email = temp_user_data.get('user', {}).get('email')

                # === 認可チェック ===
                if temp_user_email and temp_user_email in ALLOWED_USERS:
                    # 許可ユーザーの場合 -> 状態を更新して再実行し、チャット画面へ
                    st.session_state.user_info = user_info_from_library
                    st.session_state.is_authorized = True
                    st.session_state.login_error = None
                    st.rerun() # ★★★ 再実行してifブロックに進む
                elif temp_user_email:
                    # === ★★★ 不許可ユーザーの場合のメッセージ ★★★ ===
                    st.error(f"アクセス拒否: {temp_user_email}")
                    st.warning("このアカウントは現在、このアプリケーションを使用する権限がありません。")
                    st.info("現在、このサービスはメンテナンス中です")
                    # ログイン状態はリセット (session_stateは更新しない)
                    st.session_state.user_info = None
                    st.session_state.is_authorized = False
                    st.session_state.login_error = "Unauthorized User" # ログインエラー状態は記録しても良い
                    # ここで rerun しないことで、エラーメッセージが表示された状態で
                    # ログインフォームが再度表示されることを期待する
                elif temp_user_data and not temp_user_data.get('success'):
                     # ログイン自体に失敗した場合
                     st.error(f"ログインに失敗しました: {temp_user_data.get('message', '不明なエラー')}")
                     st.session_state.user_info = None
                     st.session_state.is_authorized = False
                     st.session_state.login_error = temp_user_data.get('message', 'Login Failed')
                else:
                     # Email取得失敗など
                     st.error("ユーザー情報の形式が不正、またはEmailが含まれていません。")
                     st.session_state.user_info = None
                     st.session_state.is_authorized = False
                     st.session_state.login_error = "Invalid User Data"

            # else:
                # login_form() が None を返した場合 (フォーム表示中)
                # 特に何もしない (再度フォームが表示されるのを待つ)
                # ログアウト直後に is_authorized が True のままならリセットする処理はここにいれても良い
                # if st.session_state.get('is_authorized'):
                #     st.session_state.is_authorized = False
                #     # st.rerun() # 不要かもしれない

        except Exception as e:
            st.error(f"Authentication process failed: {e}")
            st.session_state.login_error = f"Authentication Error: {e}"
            st.session_state.user_info = None
            st.session_state.is_authorized = False