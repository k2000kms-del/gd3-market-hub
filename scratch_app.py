import streamlit as st
import plotly.graph_objects as go
import streamlit.components.v1 as components

st.title("Plotly JS Click: on_select=rerun vs Native")

# 1. Native Chart (no on_select)
st.write("### Chart 1: Native (No on_select)")
fig1 = go.Figure()
fig1.add_trace(go.Bar(
    y=['A', 'B'], x=[10, 20], orientation='h',
    customdata=[['codeA', 'nameA'], ['codeB', 'nameB']],
    hovertemplate="Name: %{y}<br>Value: %{x}<extra></extra>"
))
fig1.update_layout(clickmode='event+select')
st.plotly_chart(fig1, key="native_chart")

# 2. Chart with on_select
st.write("### Chart 2: With on_select='rerun'")
fig2 = go.Figure()
fig2.add_trace(go.Bar(
    y=['X', 'Y'], x=[15, 25], orientation='h',
    customdata=[['codeX', 'nameX'], ['codeY', 'nameY']],
    hovertemplate="Name: %{y}<br>Value: %{x}<extra></extra>"
))
fig2.update_layout(clickmode='event+select')
st.plotly_chart(fig2, on_select='rerun', selection_mode=['points'], key="rerun_chart")

# Hidden text input
st.text_input("js_helper", key="js_helper", value="")
st.write("JS Helper Value:", st.session_state.js_helper)

# JS code
js_code = """
<script>
(function() {
    var parentDoc = window.parent.document;
    
    function setupListeners() {
        var plots = parentDoc.querySelectorAll('.js-plotly-plot');
        plots.forEach(function(plot) {
            if (plot && !plot.getAttribute('data-click-listener-bound')) {
                plot.setAttribute('data-click-listener-bound', 'true');
                console.log("Found plotly chart, binding plotly_click:", plot.id);
                
                plot.on('plotly_click', function(data) {
                    console.log("plotly_click fired on:", plot.id, data);
                    if (data && data.points && data.points.length > 0) {
                        var pt = data.points[0];
                        var yVal = pt.y;
                        var custom = pt.customdata;
                        var outputStr = yVal + "," + (custom ? custom.join(',') : '');
                        
                        var inputs = parentDoc.querySelectorAll('input');
                        var targetInput = null;
                        inputs.forEach(function(input) {
                            var ariaLabel = input.getAttribute('aria-label') || "";
                            if (input.id.includes("js_helper") || ariaLabel.includes("js_helper")) {
                                targetInput = input;
                            }
                        });
                        
                        if (targetInput) {
                            // React setter bypass
                            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                            nativeInputValueSetter.call(targetInput, outputStr);
                            targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                            targetInput.dispatchEvent(new Event('change', { bubbles: true }));
                            var ke = new KeyboardEvent('keydown', {
                                bubbles: true, cancelable: true, keyCode: 13, key: 'Enter'
                            });
                            targetInput.dispatchEvent(ke);
                        }
                    }
                });
            }
        });
    }
    
    setInterval(setupListeners, 1000);
})();
</script>
"""
components.html(js_code, height=0)
st.button("Rerun")
