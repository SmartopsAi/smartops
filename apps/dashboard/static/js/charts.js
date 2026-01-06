// Color Palette
const COLORS = {
    primary: '#1C4D8D', // Series 1
    accent: '#4988C4',  // Series 2
    deep: '#0F2854',    // Series 3
    bg: '#BDE8F5'       // Fill/Area
};

/**
 * Renders the Anomaly Score trend line.
 * @param {string} canvasId - DOM ID of the canvas element
 * @param {Array} labels - X-axis labels
 * @param {Array} dataPoints - Y-axis values
 */
function renderAnomalyChart(canvasId, labels, dataPoints) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Anomaly Score',
                data: dataPoints,
                borderColor: COLORS.primary,
                backgroundColor: COLORS.bg, // Soft blue fill
                fill: true,
                tension: 0.4, // Smooth curve
                pointRadius: 3,
                pointBackgroundColor: COLORS.deep
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 1.0,
                    grid: {
                        color: '#f0f0f0'
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            }
        }
    });
}

// // Auto-initialize charts if data is present (example hook)
// document.addEventListener('DOMContentLoaded', () => {
//     // Check if we are on a page that needs dummy data for initial render
//     const overviewCanvas = document.getElementById('chart-overview-anomaly');
//     if (overviewCanvas) {
//         // Render a placeholder chart until API data loads
//         // Real implementation would pass data into this function
//         renderAnomalyChart('chart-overview-anomaly', 
//             ['10:00', '10:05', '10:10', '10:15', '10:20', '10:25'], 
//             [0.1, 0.12, 0.08, 0.65, 0.9, 0.85] 
//         );
//     }
// });