import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import google.auth.transport.requests
import os
import json
import re
import pandas as pd
from openai import OpenAI

client = OpenAI(
    # This is the default and can be omitted
    api_key=st.secrets["openai_api_key"],
)

# Google APIキーを入力
API_KEY = st.secrets["google_api_key"]

# YouTube APIのクライアントを作成
youtube = build('youtube', 'v3', developerKey=API_KEY)

with open("./client_secret.json", 'w', encoding='utf-8') as output_file:
    output_file.write(st.secrets["client_secret"])

# OAuth 2.0 クライアント ID 情報を含む JSON ファイルを指定
CLIENT_SECRETS_FILE = "./client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/youtube.readonly']
REDIRECT_URI = 'https://getnews-mcn.streamlit.app/'  # ルートURLに変更
redirect_url = "https://getnews-mcn.streamlit.app/"

def get_top_videos(channel_id, max_results=10):
    # チャンネルのアップロード動画リストを取得
    response = youtube.channels().list(
        part='contentDetails',
        id=channel_id
    ).execute()

    uploads_playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    # 再生回数上位の動画を取得
    response = youtube.playlistItems().list(
        part='snippet,contentDetails',
        playlistId=uploads_playlist_id,
        maxResults=max_results
    ).execute()

    videos = []
    for item in response['items']:
        video_id = item['contentDetails']['videoId']
        video_title = item['snippet']['title']

        # 再生回数を取得
        video_response = youtube.videos().list(
            part='statistics',
            id=video_id
        ).execute()

        view_count = int(video_response['items'][0]['statistics']['viewCount'])
        videos.append((video_title, view_count))

    # 再生回数でソート
    videos.sort(key=lambda x: x[1], reverse=True)
    return videos

def get_video_id(youtube_url):
    # YouTubeのURLから動画IDを抽出する正規表現
    video_id_match = re.search(r'v=([a-zA-Z0-9_-]+)', youtube_url)
    if video_id_match:
        return video_id_match.group(1)
    short_url_match = re.search(r'youtu.be/([a-zA-Z0-9_-]+)', youtube_url)
    if short_url_match:
        return short_url_match.group(1)
    return None

def get_video_description(video_id, api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.videos().list(part='snippet', id=video_id)
    response = request.execute()
    if 'items' in response and len(response['items']) > 0:
        return response['items'][0]['snippet']['description']
    return 'Description not found'

#タイトルを生成
def create_description(subtitles, video_descriptions):
    variable1 = subtitles.replace('\n', '')
    variable2 = variable1.replace(' ', '')
    response = client.chat.completions.create(
      #プロンプト
      messages=[
        {
          "role": "system",
          "content":
f'''
あなたのタスクは与えられたYouTube動画の文字起こしの文字列から、動画の説明欄を生成することです。
'''
        },
        {
          "role": "user",
          "content":
f'''
以下のYouTubeの動画の文字起こしの文字列から、動画の説明欄を生成してください。
ただし、動画の内容を踏まえた上で、以下に提示する過去の動画の説明欄で記述されているフォーマットに従って生成してください。

## YouTube動画の字幕の文字列

{variable2}


## 過去の動画の説明欄で記述されているフォーマット

{video_descriptions}
'''
        }
      ],
      #使用モデル
      model="gpt-4o-2024-05-13",
      #ランダム性(0固定)
      temperature=0.2,
      #選択肢を絞る
      top_p=1,
    )
    return response.choices[0].message.content

#タイトルを生成
def create_title(description, title_list):
    response = client.chat.completions.create(
      #プロンプト
      messages=[
        {
          "role": "system",
          "content":
f'''
あなたのタスクは与えられた動画の内容から、YouTubeの動画のタイトルとして適切なものを出力することです。
'''
        },
        {
          "role": "user",
          "content":
f'''
以下の内容のYouTubeの動画を作成することを考えた時に、動画の内容に沿った動画のタイトルをどのように設定すると良いですか？動画内で話されている面白い発言にもう留意しながらクリックしたくなるようなものを20個ほど提案してください。
なお、以下の過去のYouTubeの動画のタイトルのリストを、言い回しやフォーマットも参考にしながら出力してください。

## YouTubeの動画の内容(動画の文字起こし)
{description}

## 過去のYouTubeの動画のタイトルのリスト
{title_list}
'''
        }
      ],
      #使用モデル
      model="gpt-4o-2024-05-13",
      #ランダム性(0固定)
      temperature=0.2,
      #選択肢を絞る
      top_p=1,
    )
    return response.choices[0].message.content

def redirect(url):
    st.markdown(f'<meta http-equiv="refresh" content="0; url={url}">', unsafe_allow_html=True)

def authenticate():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(prompt='consent')
    return auth_url, state

def get_credentials(flow, code):
    flow.fetch_token(code=code)
    return flow.credentials

def get_youtube_service(credentials):
    youtube = build('youtube', 'v3', credentials=credentials)
    return youtube

def main():
    st.title("タイトル・動画説明欄生成")
    st.caption("動画の文字起こしから動画のタイトルと動画の説明欄の生成をします。")

    if 'credentials' not in st.session_state:
        st.session_state.credentials = None
    if 'state' not in st.session_state:
        st.session_state.state = None

    if st.session_state.credentials is None:
        try:
          query_params = st.experimental_get_query_params()
          if 'code' not in query_params:
              auth_url, state = authenticate()
              st.session_state.state = state
              st.write(f"こちらからYouTubeのログイン連携をしてください: [YouTubeログイン連携]({auth_url})")
          else:
              code = query_params['code'][0]
              flow = Flow.from_client_secrets_file(
                  CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
              )
              flow.fetch_token(code=code)
              credentials = flow.credentials
              st.session_state.credentials = credentials
              youtube_service = get_youtube_service(st.session_state.credentials)
              request = youtube_service.channels().list(part="snippet,contentDetails,statistics", mine=True)
              response = request.execute()
              channel_id = response['items'][0]['id']
              channel_name = response['items'][0]['snippet']['title']
              st.success(channel_name+"さんのログイン連携に成功しました")
              #st.write(channel_name+"さん")
              with st.form('my_form'):
                text = st.text_area('ここに文字起こしのテキストを貼り付けてください。改行が入らなくても大丈夫です。')
                youtube_url = st.text_input('動画の説明欄を参考にする動画のURL:')
                if youtube_url:
                  video_id = get_video_id(youtube_url)
                  if video_id:
                      descriptions = get_video_description(video_id, API_KEY)
                      with st.expander("参考にする動画の説明欄"):
                        st.code(descriptions)
                  else:
                      st.warning('YouTubeの動画のURLが不正です', icon="🚨")
                submitted = st.form_submit_button('Submit')
                if submitted:
                  with st.spinner("生成中..."):
                      top_videos = get_top_videos(channel_id)
                      # タイトルのみを取り出し箇条書きのテキストを作成
                      titles = [title for title, _ in top_videos]
                      titles_text = '\n'.join(f'- {title}' for title in titles)
                      description = create_description(text, descriptions)
                      with st.expander("【動画の説明】"):
                        st.code(description)
                      titile_list = create_title(description, titles_text)
                      with st.expander("【動画のタイトルリスト】"):
                        st.code(titile_list)
        except:
            redirect(redirect_url)
    else:
        try:
              youtube_service = get_youtube_service(st.session_state.credentials)
              request = youtube_service.channels().list(part="snippet,contentDetails,statistics", mine=True)
              response = request.execute()
              channel_id = response['items'][0]['id']
              channel_name = response['items'][0]['snippet']['title']
              st.success(channel_name+"さんのログイン連携に成功しました")
              with st.form('my_form'):
                text = st.text_area('ここに文字起こしのテキストを貼り付けてください。改行が入らなくても大丈夫です。')
                youtube_url = st.text_input('動画の説明欄を参考にする動画のURL:')
                if youtube_url:
                  video_id = get_video_id(youtube_url)
                  if video_id:
                      descriptions = get_video_description(video_id, API_KEY)
                      with st.expander("参考にする動画の説明欄"):
                        st.code(descriptions)
                  else:
                      st.warning('YouTubeの動画のURLが不正です', icon="🚨")
                submitted = st.form_submit_button('Submit')
                if submitted:
                  with st.spinner("生成中..."):
                      top_videos = get_top_videos(channel_id)
                      # タイトルのみを取り出し箇条書きのテキストを作成
                      titles = [title for title, _ in top_videos]
                      titles_text = '\n'.join(f'- {title}' for title in titles)
                      description = create_description(text, descriptions)
                      with st.expander("【動画の説明】"):
                        st.code(description)
                      titile_list = create_title(description, titles_text)
                      with st.expander("【動画のタイトルリスト】"):
                        st.code(titile_list)
            
        except Exception as e:
            # セッションエラーが発生した場合、特定のURLにリダイレクト
            redirect(redirect_url)
            st.experimental_rerun()

if __name__ == "__main__":
    main()
