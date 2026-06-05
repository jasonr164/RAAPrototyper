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

# ✅ Multi-resource expansion (analysis only)
def expand_resources(df):
    rows = []
    for _, r in df.iterrows():
        for res in str(r['Resource']).split(','):
            new = r.copy()
            new['Resource'] = res.strip()
            rows.append(new)
    return pd.DataFrame(rows)

# -----------------------------
# Step Plot (FIXED segmentation)
# -----------------------------
def square_wave_step_plot(all_tasks, resource, capacity, x_min, x_max):
    df = all_tasks[all_tasks['Resource'] == resource].sort_values('Start date')

    changes = []
    for _, row in df.iterrows():
        changes.append((row['Start date'], 1, row['Title']))
        changes.append((row['End date'], -1, row['Title']))

    changes.sort()

    times, usage, active_tasks = [], [], []
    current = 0
    active = set()

    for t, delta, title in changes:
        times.append(t)
        usage.append(current)
        active_tasks.append(", ".join(active))

        if delta == 1:
            active.add(title)
        else:
            active.discard(title)

        current += delta

        times.append(t)
        usage.append(current)
        active_tasks.append(", ".join(active))

    if not times:
        return go.Figure()

    step_df = pd.DataFrame({
        'time': times,
        'usage': usage,
        'tasks': active_tasks
    })

    fig = go.Figure()

    # Base line
    fig.add_trace(go.Scatter(
        x=step_df['time'],
        y=step_df['usage'],
        mode='lines',
        line=dict(shape='hv', width=3, color='blue'),
        customdata=step_df['tasks'],
        hovertemplate="Usage=%{y}<br>Tasks=%{customdata}<extra></extra>",
        name=resource
    ))

    # ✅ FIXED: segment conflict lines
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
        yaxis=dict(dtick=1),
        height=350
    )

    return fig

# -----------------------------
# Session State
# -----------------------------
if "all_tasks" not in st.session_state:
    st.session_state.all_tasks = pd.DataFrame(
        columns=['Title', 'Start date', 'End date', 'Resource', 'Source']
    )

if "hide_tasks" not in st.session_state:
    st.session_state.hide_tasks = set()

if "resource_caps" not in st.session_state:
    st.session_state.resource_caps = {}

if "hide_step_plots" not in st.session_state:
    st.session_state.hide_step_plots = set()

# -----------------------------
# App UI
# -----------------------------
st.title("Resource Gantt Comparison Tool - Version B5")

uploaded_files = st.file_uploader(
    "Upload Gantt chart files",
    type=['csv', 'xls', 'xlsx'],
    accept_multiple_files=True
)

# -----------------------------
# File Load (WITH Source)
# -----------------------------
if uploaded_files:
    fresh_tasks = pd.DataFrame(
        columns=['Title', 'Start date', 'End date', 'Resource', 'Source']
    )

    for i, file in enumerate(uploaded_files):
        df = parse_gantt_file(file)
        df['Resource'] = df['Title']
        df['Source'] = extract_source(file.name, i)

        fresh_tasks = pd.concat([fresh_tasks, df], ignore_index=True)

    for col in ['Start date', 'End date']:
        if np.issubdtype(fresh_tasks[col].dtype, np.number):
            fresh_tasks[col] = fresh_tasks[col].apply(excel_date)
        else:
            fresh_tasks[col] = pd.to_datetime(fresh_tasks[col], errors='coerce')

    fresh_tasks = fresh_tasks.dropna()

    st.session_state.all_tasks = pd.concat(
        [st.session_state.all_tasks, fresh_tasks],
        ignore_index=True
    ).drop_duplicates()

tasks = st.session_state.all_tasks.copy()

# -----------------------------
# Tasks Table
# -----------------------------
st.subheader("Tasks Loaded")

if not tasks.empty:

    if "edit_buffer" not in st.session_state:
        st.session_state.edit_buffer = tasks.copy()
        st.session_state.edit_buffer['Hide'] = st.session_state.edit_buffer.index.isin(
            st.session_state.hide_tasks
        )

    edited_df = st.data_editor(
        st.session_state.edit_buffer,
        use_container_width=True,
        height=400
    )

    colA, colB = st.columns(2)

    with colA:
        if st.button("✅ Apply Changes"):
            st.session_state.all_tasks = edited_df.drop(columns=["Hide"])
            st.session_state.hide_tasks = set(edited_df["Hide"].loc[edited_df["Hide"]].index)

            st.session_state.edit_buffer = st.session_state.all_tasks.copy()
            st.session_state.edit_buffer['Hide'] = st.session_state.edit_buffer.index.isin(
                st.session_state.hide_tasks
            )

    with colB:
        if st.button("↩ Reset Edits"):
            st.session_state.edit_buffer = tasks.copy()
            st.session_state.edit_buffer['Hide'] = st.session_state.edit_buffer.index.isin(
                st.session_state.hide_tasks
            )

    display_tasks = edited_df[~edited_df["Hide"]]

else:
    display_tasks = tasks

# ✅ Multi-resource expansion for analysis
expanded_tasks = expand_resources(display_tasks)
final_tasks = expanded_tasks.copy()

# -----------------------------
# Resource Capacity
# -----------------------------
st.subheader("Resource Capacity Settings")

resources = sorted(final_tasks['Resource'].unique())

for r in resources:
    if r not in st.session_state.resource_caps:
        st.session_state.resource_caps[r] = 1

    st.session_state.resource_caps[r] = st.number_input(
        r,
        min_value=1,
        value=st.session_state.resource_caps[r],
        key=f"cap_{r}"
    )

# -----------------------------
# Analyze
# -----------------------------
if st.button("Analyze"):
    st.session_state.analyzed = True

if st.session_state.get("analyzed", False) and not final_tasks.empty:

    # ✅ Gantt view toggle
    view_mode = st.radio(
        "Gantt View",
        ["Conflict View", "Timeline View"],
        horizontal=True
    )

    st.subheader("Combined Gantt Chart")

    resource_order = (
        final_tasks.groupby("Resource")["Start date"]
        .min()
        .sort_values()
        .index.tolist()
    )

    final_tasks["Resource"] = pd.Categorical(
        final_tasks["Resource"],
        categories=resource_order,
        ordered=True
    )

    final_tasks = final_tasks.sort_values(by=["Resource", "Start date"])

    fig = px.timeline(
        final_tasks,
        x_start="Start date",
        x_end="End date",
        y="Resource",
        color="Resource" if view_mode == "Conflict View" else "Source",
        hover_data=["Title", "Source"]
    )

    fig.update_yaxes(
        categoryorder="array",
        categoryarray=resource_order,
        autorange="reversed"
    )

    # ✅ Add conflict highlighting overlay
    if view_mode == "Conflict View":
        for r in resources:
            df_r = final_tasks[final_tasks['Resource'] == r]
            events = []

            for _, row in df_r.iterrows():
                events.append((row['Start date'], 1))
                events.append((row['End date'], -1))

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
                        fillcolor="red",
                        opacity=0.3,
                        line_width=0
                    )

    st.plotly_chart(fig, width="stretch")

    # -----------------------------
    # Step Plots
    # -----------------------------
    st.subheader("Step Plot Visualizations")

    gantt_x0 = final_tasks['Start date'].min()
    gantt_x1 = final_tasks['End date'].max()

    for resource in resources:
        if resource not in st.session_state.hide_step_plots:
            fig_step = square_wave_step_plot(
                final_tasks,
                resource,
                st.session_state.resource_caps[resource],
                gantt_x0,
                gantt_x1
            )
            st.plotly_chart(fig_step, width="stretch")

    # -----------------------------
    # Conflict Summary (ENHANCED)
    # -----------------------------
    st.subheader("Conflict Summary")

    conflicts = []

    for resource in resources:
        df = final_tasks[final_tasks['Resource'] == resource]

        events = []
        for _, row in df.iterrows():
            events.append((row['Start date'], 1, row['Title']))
            events.append((row['End date'], -1, row['Title']))

        events.sort()

        current = 0
        active = set()

        for t, delta, title in events:
            if delta == 1:
                active.add(title)
            else:
                active.discard(title)

            current += delta

            if current > st.session_state.resource_caps[resource]:
                conflicts.append((
                    resource,
                    t,
                    current,
                    ", ".join(active)
                ))

    if conflicts:
        st.dataframe(
            pd.DataFrame(conflicts, columns=["Resource", "Time", "Usage", "Tasks"])
        )
    else:
        st.success("No conflicts detected ✅")

else:
    st.info("Upload files and click Analyze.")

st.markdown("---")
st.caption("Upload, edit, assign resources, and analyze conflicts.")
