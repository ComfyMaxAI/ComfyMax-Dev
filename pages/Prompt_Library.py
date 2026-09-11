from datetime import datetime
from pathlib import Path
import sqlite3

import streamlit as st
from modules.prompt_library import PromptLibrary

ROOT = Path(__file__).resolve().parents[1]
st.set_page_config(page_title='Prompt Library · ComfyMax', page_icon='📚', layout='wide')
st.title('Prompt Library')
st.caption('Only prompts you explicitly approve and save appear here.')
st.page_link('App.py', label='Back to prompt generation', icon='🎬')
library = PromptLibrary(ROOT / 'data' / 'prompt_library.sqlite3')

try:
    rows = library.list()
except (OSError, sqlite3.Error):
    st.error('The local Prompt Library could not be opened. Check disk space and folder permissions.')
    st.stop()

if st.session_state.pop('library_deleted', False):
    st.success('Prompt deleted.')
if not rows:
    st.info('No saved prompts yet. Approve a final prompt on the generation page, then choose Save approved prompt.')
    st.stop()

query = st.text_input('Search prompts', placeholder='Search text, model, workflow or date')
workflow = st.selectbox('Workflow', [None] + sorted({r['workflow'] for r in rows}),
                        format_func=lambda v: 'All workflows' if v is None else v or 'Unspecified')
prompt_type = st.selectbox('Type', [None] + sorted({r['prompt_type'] for r in rows}),
                           format_func=lambda v: 'All types' if v is None else v or 'Unspecified')
filtered = [r for r in rows if (workflow is None or r['workflow'] == workflow)
            and (prompt_type is None or r['prompt_type'] == prompt_type)
            and query.strip().casefold() in ' '.join(str(v) for v in r.values()).casefold()]
st.caption(f'{len(filtered)} saved prompt(s)')
if not filtered:
    st.info('No prompts match these filters.')
    st.stop()

page_count = (len(filtered) + 9) // 10
page = st.selectbox('Page', range(1, page_count + 1))
for row in filtered[(page - 1) * 10:page * 10]:
    with st.container(border=True):
        stamp = datetime.fromisoformat(row['created_at']).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
        st.caption(' · '.join([stamp, row['workflow'] or 'No workflow',
                              row['prompt_type'] or 'No type', row['model'] or 'No model']))
        st.code(row['prompt'], language=None, wrap_lines=True)
        st.caption('Use the copy icon in the prompt box to copy the complete text.')
        if st.button('Reuse prompt', key='reuse_' + row['id'], use_container_width=True):
            st.session_state['library_reuse'] = row
            st.switch_page('App.py')
        if st.button('Delete prompt', key='delete_' + row['id'], use_container_width=True):
            st.session_state['library_delete_pending'] = row['id']
        if st.session_state.get('library_delete_pending') == row['id']:
            st.warning('Permanently delete this saved prompt?')
            if st.button('Confirm delete', key='confirm_' + row['id'], type='primary', use_container_width=True):
                try:
                    library.delete(row['id'])
                except (OSError, sqlite3.Error):
                    st.error('Could not delete the prompt. Please try again.')
                else:
                    st.session_state.pop('library_delete_pending', None)
                    st.session_state['library_deleted'] = True
                    st.rerun()
            if st.button('Cancel', key='cancel_' + row['id'], use_container_width=True):
                st.session_state.pop('library_delete_pending', None)
                st.rerun()
