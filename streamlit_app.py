import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.graph_objects as go
import plotly.express as px

# -----------------------------
# File parsing + SOURCE tagging
# -----------------------------
def extract_source(name, idx):
    match = re.search(r'\d{4}(\.\d+)?', name)
    return match.group(0) if match else f"File {idx+1}"

def parse_gantt_file(uploaded_file, idx):
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    df['Source'] = extract_source(uploaded_file.name, idx)
    df['Resource'] = df['Title']

    return df[['Title', 'Start date', 'End date', 'Resource', 'Source']]

# -----------------------------
def excel_date(num):
    return pd.Timestamp('1899-12-30') + pd.to_timedelta(num, unit='D')

# -----------------------------
# Expand multi-resource
# -----------------------------
def expand_resources(df):
    rows = []
    for _, r in df.iterrows():
        resources = [x.strip() for x in str(r['Resource']).split(',')]
        for res in resources:
            new = r.copy()
            new['Resource'] = res
            rows.append(new)
    return pd.DataFrame(rows)

# -----------------------------
# Build usage timeline WITH task context
# -----------------------------
def build_usage(df, resource):
    events = []

    for _, r in df[df['Resource']==resource].iterrows():
        events.append((r['Start date'], 1, r['Title']))
        events.append((r['End date'], -1, r['Title']))

    events.sort()
    active = set()

    timeline = []
    usage = 0

    for t, delta, title in events:
        timeline.append((t, usage, list(active)))

        if delta == 1:
            active.add(title)
        else:
            active.discard(title)

        usage += delta

        timeline.append((t, usage, list(active)))

    return timeline

# -----------------------------
# Step Plot (fixed segments)
# -----------------------------
def square_wave_step_plot(df, resource, capacity, x0, x1):

    timeline = build_usage(df, resource)

    times, values, labels = [], [], []

    for t,u,tasks in timeline:
        times.append(t)
        values.append(u)
        labels.append(", ".join(tasks))

    fig = go.Figure()

    # base line
    fig.add_trace(go.Scatter(
        x=times,
        y=values,
        mode='lines',
        line=dict(shape='hv', width=3, color='blue'),
        customdata=labels,
        hovertemplate="Usage:%{y}<br>Tasks:%{customdata}"
    ))

    # ✅ isolate ONLY conflict segments
    for i in range(len(times)-1):
        if values[i] > capacity:
            fig.add_trace(go.Scatter(
                x=[times[i], times[i+1]],
                y=[values[i], values[i+1]],
                mode='lines',
                line=dict(shape='hv', width=4, color='red'),
                showlegend=False,
                customdata=[labels[i], labels[i]],
                hovertemplate="Conflict<br>Usage:%{y}<br>Tasks:%{customdata}"
            ))

    fig.add_hline(y=capacity, line_dash='dash', line_color='red')

    fig.update_layout(
        title=resource,
        xaxis=dict(range=[x0,x1]),
        yaxis=dict(dtick=1),
        height=300
    )

    return fig

# -----------------------------
# Conflict extraction
# -----------------------------
def extract_conflicts(df, capacity):
    timeline = build_usage(df, df['Resource'].iloc[0])
    rows = []

    for t,u,tasks in timeline:
        if u > capacity:
            rows.append({
                "Time": t,
                "Usage": u,
                "Tasks": ", ".join(tasks)
            })
    return rows

# -----------------------------
# Session State
# -----------------------------
if "all_tasks" not in st.session_state:
    st.session_state.all_tasks = pd.DataFrame(
        columns=['Title','Start date','End date','Resource','Source']
    )

if "resource_caps" not in st.session_state:
    st.session_state.resource_caps = {}

# -----------------------------
# UI
# -----------------------------
st.title("Resource Gantt Tool - Version B5")

uploaded_files = st.file_uploader(
    "Upload files",
    type=['csv','xls','xlsx'],
    accept_multiple_files=True
)

if uploaded_files:
    new_data = pd.DataFrame()

    for i,f in enumerate(uploaded_files):
        df = parse_gantt_file(f,i)
        new_data = pd.concat([new_data,df])

    for col in ['Start date','End date']:
        if np.issubdtype(new_data[col].dtype,np.number):
            new_data[col]=new_data[col].apply(excel_date)
        else:
            new_data[col]=pd.to_datetime(new_data[col])

    st.session_state.all_tasks = pd.concat(
        [st.session_state.all_tasks,new_data],ignore_index=True
    )

tasks = st.session_state.all_tasks.copy()

# -----------------------------
# Table
# -----------------------------
st.subheader("Tasks Loaded")

edited = st.data_editor(tasks, use_container_width=True)

display_tasks = edited.copy()

# -----------------------------
# Expand resources
# -----------------------------
expanded = expand_resources(display_tasks)

# -----------------------------
# Resource capacity
# -----------------------------
resources = sorted(expanded['Resource'].unique())

for r in resources:
    if r not in st.session_state.resource_caps:
        st.session_state.resource_caps[r]=1

    st.session_state.resource_caps[r] = st.number_input(
        f"{r}",
        min_value=1,
        value=st.session_state.resource_caps[r],
        key=f"cap_{r}"
    )

# -----------------------------
# Analyze
# -----------------------------
if st.button("Analyze"):

    x0 = expanded['Start date'].min()
    x1 = expanded['End date'].max()

    # -----------------------------
    st.subheader("Combined Gantt")

    fig = px.timeline(
        expanded,
        x_start="Start date",
        x_end="End date",
        y="Resource",
        color="Source",
        hover_data=["Title","Source"]
    )

    # ✅ overlay conflict segments
    for r in resources:
        df_r = expanded[expanded['Resource']==r]

        timeline = build_usage(df_r, r)
        cap = st.session_state.resource_caps[r]

        for i in range(len(timeline)-1):
            t,u,_ = timeline[i]
            t2 = timeline[i+1][0]

            if u > cap:
                fig.add_shape(
                    type="rect",
                    x0=t, x1=t2,
                    y0=r, y1=r,
                    xref='x',
                    yref='y',
                    fillcolor="red",
                    opacity=0.3,
                    line_width=0
                )

    fig.update_yaxes(autorange='reversed')

    st.plotly_chart(fig, width="stretch")

    # -----------------------------
    st.subheader("Step Plots")

    for r in resources:
        fig = square_wave_step_plot(
            expanded,
            r,
            st.session_state.resource_caps[r],
            x0,x1
        )
        st.plotly_chart(fig, width="stretch")

    # -----------------------------
    st.subheader("Conflict Summary")

    all_conflicts = []

    for r in resources:
        df_r = expanded[expanded['Resource']==r]
        rows = extract_conflicts(df_r, st.session_state.resource_caps[r])

        for row in rows:
            row["Resource"]=r
            all_conflicts.append(row)

    if all_conflicts:
        st.dataframe(pd.DataFrame(all_conflicts))
    else:
        st.success("No conflicts ✅")
