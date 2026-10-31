import streamlit as st

from copilot.review import MAX_BYTES, explain_with_llm, review_code

st.set_page_config(page_title='Cynbit PR Review Copilot', page_icon='🔎', layout='wide')
st.title('Cynbit AI PR Review Copilot')
st.caption('Assessment prototype • Python source review • Human judgment required')
st.info('Paste one complete Python file. Code is analyzed, never executed. Temporary source files '
        'are deleted after analysis. Avoid confidential code. This prototype does not fetch pull requests.')
code = st.text_area('Python source', height=300, max_chars=MAX_BYTES,
                    value='def append_item(item, items=[]):\n    items.append(item)\n    return items\n')
consent = st.checkbox('Send this source and findings to OpenAI for optional AI commentary', value=False)
st.caption('Requires a server-configured API key. No key is needed for Ruff, Bandit or AST checks.')
if st.button('Review code', type='primary'):
    try:
        with st.spinner('Analyzing source…'):
            result = review_code(code)
        st.subheader(f'{len(result.findings)} findings')
        st.json(result.status)
        if result.findings:
            st.dataframe([f.model_dump() for f in result.findings], hide_index=True,
                         use_container_width=True)
        else:
            st.success('No findings from completed checks. This does not establish that the code is safe.')
        st.download_button('Download review JSON', result.model_dump_json(indent=2),
                           file_name='review.json', mime='application/json')
        if consent:
            st.subheader('AI commentary — unverified suggestions')
            st.text(explain_with_llm(result, code, consent=True))
    except ValueError as error:
        st.error(str(error))
