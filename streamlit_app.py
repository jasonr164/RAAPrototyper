import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import re

# -----------------------------
# Helpers
# -----------------------------
def parse_gantt_file(uploaded_file):
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    required_cols = ['Title', 'Start date', 'End date']
    if not all(col in df.columns for col in required_cols):
        st.error(f"File {uploaded_file.name} missing columns")
        return pd.DataFrame(columns=required_cols)

    return df[required_cols]

def extract_source(name, idx):
    match = re.search(r'\d{4}(\.\d+)?', name)
    return match.group(0) if match else f"File {idx+1}"

def excel_date(num):
    return pd.Timestamp('1899-12-30') + pd.to_timedelta(num, unit='D')

def expand_resources(df):
    rows = []
    for _, r in df.iterrows():
        for res in str(r['Resource']).split(','):
            new = r.copy()
            new['Resource'] = res.strip()
            rows.append(new)
    return pd.DataFrame(rows)

# -----------------------------
# Step Plot (fixed)
# -----------------------------
def square_wave_step_plot(all_tasks, resource, capacity, x_min, x_max):
    df = all_tasks[all_tasks['Resource'] == resource]

    changes = []
    for _, row in df.iterrows():
        changes.append((row['Start date'], 1))
        changes.append((row['End date'], -1))

    changes.sort()

    times, usage = [], []
    current = 0

    for t, delta in changes:
        times.append(t)
        usage.append(current)
        current += delta
        times.append(t)
        usage.append(current)

    step_df = pd.DataFrame({'time': times, 'usage': usage})

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=step_df['time'],
        y=step_df['usage'],
        mode='lines',
        line=dict(shape='hv', width=3, color='blue')
    ))

    # ✅ conflict segments only
    for i in range(len(step_df) - 1):
        if step_df['usage'].iloc[i] > capacity:
            fig.add_trace(go.Scatter(
                x=[step_df['time'].iloc[i], step_df['time'].iloc[i+1]],
                y=[step_df['usage'].iloc[i], step_df['usage'].iloc[i+1]],
                mode='lines',
                line=dict(shape='hv', width=4, color='red'),
                showlegend=False
            ))

    fig.add_hline(y=capacity, line_dash="dash", line_color="red")

    fig.update_layout(
        title=resource,
        xaxis=dict(range=[x_min, x_max]),
        yaxis=dict(dtick=1),
        height=300
    )

    return fig

# -----------------------------
# Session State
# -----------------------------
if "all_tasks" not in st.session_state:
    st.session_state.all_tasks = pd.DataFrame(
        columns=['Title','Start date','End date','Source','Resource']
    )

if "hide_tasks" not in st.session_state:
    st.session_state.hide_tasks = set()

if "resource_caps" not in st.session_state:
    st.session_state.resource_caps = {}

if "hidden_resources" not in st.session_state:
    st.session_state.hidden_resources = set()

# -----------------------------
# UI
# -----------------------------
st.title("Resource Gantt Tool - B5.1")

uploaded_files = st.file_uploader(
    "Upload files",
    accept_multiple_files=True
)

# -----------------------------
# Load Files
# -----------------------------
if uploaded_files:
    new_tasks = pd.DataFrame()

    for i, f in enumerate(uploaded_files):
        df = parse_gantt_file(f)
        df["Resource"] = df["Title"]
        df["Source"] = extract_source(f.name, i)
        new_tasks = pd.concat([new_tasks, df])

    for col in ['Start date','End date']:
        if np.issubdtype(new_tasks[col].dtype,np.number):
            new_tasks[col] = new_tasks[col].apply(excel_date)
        else:
            new_tasks[col] = pd.to_datetime(new_tasks[col])

    st.session_state.all_tasks = pd.concat(
        [st.session_state.all_tasks, new_tasks],
        ignore_index=True
    )

tasks = st.session_state.all_tasks.copy()

# -----------------------------
# Tasks Table (formatted)
# -----------------------------
st.subheader("Tasks Loaded")

tasks_display = tasks.copy()
tasks_display['Start date'] = tasks_display['Start date'].dt.date
tasks_display['End date'] = tasks_display['End date'].dt.date

# ✅ reorder columns
tasks_display = tasks_display[['Title','Start date','End date','Source','Resource']]

edited = st.data_editor(tasks_display, height=400)

display_tasks = tasks.iloc[edited.index]

# -----------------------------
# Expand resources
# -----------------------------
expanded = expand_resources(display_tasks)

# -----------------------------
# Resource Settings (compact)
# -----------------------------
st.subheader("Resource Capacity Settings")

resources = sorted(expanded['Resource'].unique())
cols = st.columns(3)

for i, r in enumerate(resources):
    col = cols[i % 3]

    if r not in st.session_state.resource_caps:
        st.session_state.resource_caps[r] = 1

    cap = col.number_input(
        r, min_value=1,
        value=st.session_state.resource_caps[r],
        key=f"cap_{r}"
    )

    st.session_state.resource_caps[r] = cap

    hide = col.checkbox("Hide", key=f"hide_{r}")

    if hide:
        st.session_state.hidden_resources.add(r)
    else:
        st.session_state.hidden_resources.discard(r)

# filter hidden
expanded = expanded[~expanded['Resource'].isin(st.session_state.hidden_resources)]

# -----------------------------
# Analyze
# -----------------------------
if st.button("Analyze"):
    st.session_state.analyzed = True

if st.session_state.get("analyzed", False):

    x0 = expanded['Start date'].min()
    x1 = expanded['End date'].max()

    view = st.radio("Gantt Mode", ["Conflict View","Timeline View"], horizontal=True)

    st.subheader("Combined Gantt Chart")

    fig = px.timeline(
        expanded,
        x_start="Start date",
        x_end="End date",
        y="Resource",
        color="Resource" if view=="Conflict View" else "Source"
    )

    # ✅ gridlines + month resolution
    fig.update_xaxes(
        showgrid=True,
        dtick="M1",
        tickformat="%b\n%Y"
    )

    fig.update_yaxes(showgrid=True, autorange="reversed")

    # ✅ conflict overlay
    if view == "Conflict View":
        for r in resources:
            df_r = expanded[expanded['Resource']==r]

            events=[]
            for _,row in df_r.iterrows():
                events.append((row['Start date'],1))
                events.append((row['End date'],-1))
            events.sort()

            current=0
            for i in range(len(events)-1):
                t,delta=events[i]
                current+=delta
                t2=events[i+1][0]

                if current > st.session_state.resource_caps[r]:
                    fig.add_shape(
                        type="rect",
                        x0=t,x1=t2,
                        y0=r,y1=r,
                        fillcolor="rgba(255,0,0,0.3)",
                        line_width=0
                    )

    st.plotly_chart(fig, width="stretch")

    # -----------------------------
    # Step Plots
    # -----------------------------
    st.subheader("Step Plot Visualizations")

    for r in sorted(expanded['Resource'].unique()):
        if r not in st.session_state.hidden_resources:
            fig_step = square_wave_step_plot(
                expanded,
                r,
                st.session_state.resource_caps[r],
                x0,x1   # ✅ same axis for all
            )
            st.plotly_chart(fig_step, width="stretch")

    # -----------------------------
    # Conflict Summary
    # -----------------------------
    st.subheader("Conflict Summary")

    conflicts=[]

    for r in resources:
        df = expanded[expanded['Resource']==r]

        events=[]
        for _,row in df.iterrows():
            events.append((row['Start date'],1,row['Title']))
            events.append((row['End date'],-1,row['Title']))

        events.sort()

        current=0
        active=set()

        for t,delta,title in events:
            if delta==1: active.add(title)
            else: active.discard(title)

            current+=delta

            if current > st.session_state.resource_caps[r]:
                conflicts.append((r,t,current,", ".join(active)))

    if conflicts:
        st.dataframe(pd.DataFrame(conflicts,columns=["Resource","Time","Usage","Tasks"]))
    else:
        st.success("No conflicts ✅")

else:
    st.info("Upload files and click Analyze")
