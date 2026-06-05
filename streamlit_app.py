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
        st.error(f"File {uploaded_file.name} missing columns: {required_cols}")
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
            new_row = r.copy()
            new_row['Resource'] = res.strip()
            rows.append(new_row)
    return pd.DataFrame(rows)

# -----------------------------
# Step Plot (correct conflict segments)
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

    if len(times) == 0:
        return go.Figure()

    step_df = pd.DataFrame({'time': times, 'usage': usage})

    fig = go.Figure()

    # Base usage
    fig.add_trace(go.Scatter(
        x=step_df['time'],
        y=step_df['usage'],
        mode='lines',
        line=dict(shape='hv', width=3, color='blue'),
        name=resource
    ))

    # ✅ Correct segmented conflicts
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
        title=f"{resource} Utilization",
        xaxis=dict(range=[x_min, x_max]),
        yaxis=dict(dtick=1),
        height=320
    )

    return fig

# -----------------------------
# Session State
# -----------------------------
if "all_tasks" not in st.session_state:
    st.session_state.all_tasks = pd.DataFrame(
        columns=['Title', 'Start date', 'End date', 'Source', 'Resource']
    )

if "resource_caps" not in st.session_state:
    st.session_state.resource_caps = {}

if "hidden_resources" not in st.session_state:
    st.session_state.hidden_resources = set()

# -----------------------------
# UI
# -----------------------------
st.title("Resource Gantt Tool - Version B5.1 (Stable)")

uploaded_files = st.file_uploader(
    "Upload Gantt files",
    type=['csv','xls','xlsx'],
    accept_multiple_files=True
)

# -----------------------------
# Load Files
# -----------------------------
if uploaded_files:
    new_tasks = pd.DataFrame()

    for i, f in enumerate(uploaded_files):
        df = parse_gantt_file(f)
        df['Resource'] = df['Title']
        df['Source'] = extract_source(f.name, i)
        new_tasks = pd.concat([new_tasks, df], ignore_index=True)

    for col in ['Start date','End date']:
        if np.issubdtype(new_tasks[col].dtype, np.number):
            new_tasks[col] = new_tasks[col].apply(excel_date)
        else:
            new_tasks[col] = pd.to_datetime(new_tasks[col], errors='coerce')

    new_tasks = new_tasks.dropna(subset=['Start date','End date'])

    st.session_state.all_tasks = pd.concat(
        [st.session_state.all_tasks, new_tasks],
        ignore_index=True
    )

tasks = st.session_state.all_tasks.copy()

# -----------------------------
# Tasks Table
# -----------------------------
st.subheader("Tasks Loaded")

tasks_display = tasks.copy()

# ✅ SAFE datetime conversion BEFORE .dt
tasks_display['Start date'] = pd.to_datetime(tasks_display['Start date'], errors='coerce')
tasks_display['End date'] = pd.to_datetime(tasks_display['End date'], errors='coerce')

tasks_display['Start date'] = tasks_display['Start date'].dt.date
tasks_display['End date'] = tasks_display['End date'].dt.date

# ✅ Reorder (as requested)
tasks_display = tasks_display[['Title', 'Start date', 'End date', 'Source', 'Resource']]

edited = st.data_editor(tasks_display, height=400, use_container_width=True)

# Preserve underlying datetime data by index
display_tasks = tasks.iloc[edited.index].copy()

# -----------------------------
# Expand multi-resource (analysis only)
# -----------------------------
expanded_tasks = expand_resources(display_tasks)

# -----------------------------
# Resource Settings (compact)
# -----------------------------
st.subheader("Resource Capacity Settings")

resources = sorted(expanded_tasks['Resource'].unique())
cols = st.columns(3)

for i, r in enumerate(resources):
    col = cols[i % 3]

    if r not in st.session_state.resource_caps:
        st.session_state.resource_caps[r] = 1

    st.session_state.resource_caps[r] = col.number_input(
        label=r,
        min_value=1,
        value=int(st.session_state.resource_caps[r]),
        key=f"cap_{r}"
    )

    hide = col.checkbox("Hide", key=f"hide_{r}")

    if hide:
        st.session_state.hidden_resources.add(r)
    else:
        st.session_state.hidden_resources.discard(r)

# Apply hide filter
expanded_tasks = expanded_tasks[
    ~expanded_tasks['Resource'].isin(st.session_state.hidden_resources)
]

# -----------------------------
# Analyze
# -----------------------------
if st.button("Analyze"):
    st.session_state.analyzed = True

if st.session_state.get("analyzed", False) and not expanded_tasks.empty:

    x0 = expanded_tasks['Start date'].min()
    x1 = expanded_tasks['End date'].max()

    view_mode = st.radio(
        "Gantt View Mode",
        ["Conflict View", "Timeline View"],
        horizontal=True
    )

    st.subheader("Combined Gantt Chart")

    # Sort resources by earliest start
    resource_order = (
        expanded_tasks.groupby("Resource")["Start date"]
        .min()
        .sort_values()
        .index.tolist()
    )

    expanded_tasks["Resource"] = pd.Categorical(
        expanded_tasks["Resource"],
        categories=resource_order,
        ordered=True
    )

    expanded_tasks = expanded_tasks.sort_values(["Resource", "Start date"])

    fig = px.timeline(
        expanded_tasks,
        x_start="Start date",
        x_end="End date",
        y="Resource",
        color="Resource" if view_mode == "Conflict View" else "Source",
        hover_data=["Title", "Source"]
    )

    # ✅ Improved gridlines + monthly resolution
    fig.update_xaxes(
        showgrid=True,
        dtick="M1",
        tickformat="%b\n%Y"
    )

    fig.update_yaxes(showgrid=True, autorange="reversed")

    # ✅ Conflict shading overlay (fixed syntax)
    if view_mode == "Conflict View":
        for r in resource_order:
            df_r = expanded_tasks[expanded_tasks["Resource"] == r]

            events = []
            for _, row in df_r.iterrows():
                events.append((row["Start date"], 1))
                events.append((row["End date"], -1))

            events.sort()

            current = 0
            for i in range(len(events) - 1):
                t, delta = events[i]
                current += delta
                t_next = events[i+1][0]

                if current > st.session_state.resource_caps[r]:
                    fig.add_shape(
                        type="rect",
                        x0=t,
                        x1=t_next,
                        y0=r,
                        y1=r,
                        xref="x",
                        yref="y",
                        fillcolor="rgba(255,0,0,0.25)",
                        line_width=0
                    )

    st.plotly_chart(fig, width="stretch")

    # -----------------------------
    # Step Plots (consistent axis)
    # -----------------------------
    st.subheader("Step Plot Visualizations")

    for r in resource_order:
        if r not in st.session_state.hidden_resources:
            fig_step = square_wave_step_plot(
                expanded_tasks,
                r,
                st.session_state.resource_caps[r],
                x0,
                x1   # ✅ same axis for all
            )
            st.plotly_chart(fig_step, width="stretch")

    # -----------------------------
    # Conflict Summary
    # -----------------------------
    st.subheader("Conflict Summary")

    conflicts = []

    for r in resource_order:
        df = expanded_tasks[expanded_tasks["Resource"] == r]

        events = []
        for _, row in df.iterrows():
            events.append((row["Start date"], 1, row["Title"]))
            events.append((row["End date"], -1, row["Title"]))

        events.sort()

        current = 0
        active = set()

        for t, delta, title in events:
            if delta == 1:
                active.add(title)
            else:
                active.discard(title)

            current += delta

            if current > st.session_state.resource_caps[r]:
                conflicts.append((r, t, current, ", ".join(active)))

    if conflicts:
        st.dataframe(
            pd.DataFrame(conflicts, columns=["Resource","Time","Usage","Tasks"])
        )
    else:
        st.success("No conflicts detected ✅")

else:
    st.info("Upload files and click Analyze.")

st.markdown("---")
st.caption("Upload, edit, assign resources, and analyze conflicts.")
