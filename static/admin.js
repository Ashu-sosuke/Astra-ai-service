document.addEventListener('DOMContentLoaded', () => {
    fetchIncidents();

    const modal = document.getElementById('detailsModal');
    const closeBtn = document.querySelector('.close-btn');
    const processAllBtn = document.getElementById('processAllBtn');

    closeBtn.onclick = function () {
        modal.style.display = "none";
    }

    if (processAllBtn) {
        processAllBtn.onclick = async function () {
            processAllBtn.disabled = true;
            processAllBtn.innerText = 'Processing...';
            try {
                const response = await fetch('/api/process-all', { method: 'POST' });
                const data = await response.json();
                alert(data.message || 'Processing started!');
                setTimeout(fetchIncidents, 3000); // Refresh after 3s
            } catch (err) {
                alert('Failed to start processing');
            } finally {
                processAllBtn.disabled = false;
                processAllBtn.innerText = 'Process Pending Incidents';
            }
        }
    }

    window.onclick = function (event) {
        if (event.target == modal) {
            modal.style.display = "none";
        }
    }
});

let allIncidents = [];

async function fetchIncidents() {
    const loader = document.getElementById('loader');
    const tbody = document.getElementById('incidentsBody');

    try {
        const response = await fetch('/api/incidents');
        if (!response.ok) throw new Error('Failed to fetch data');

        const data = await response.json();
        const incidentsRoot = data.incidents || [];
        allIncidents = incidentsRoot.map(inc => {
            const ai = inc.ai_analysis || {};
            const rawTs = ai.timestamp || inc.timestamp || inc.created_at || null;
            
            // Map legacy fields if new ones are missing
            const transcript = ai.transcript || inc.transcript || inc.transcription || 'No transcript available';
            const fusionScore = ai.severityScore || inc.severity_score || inc.fusion_score || 0;
            const severity = ai.finalSeverity || inc.final_severity || inc.finalSeverity || 
                            (fusionScore > 0.7 ? 'CRITICAL' : (fusionScore > 0.4 ? 'MEDIUM' : 'LOW'));
            const threatType = ai.threatType || inc.threat_type || inc.threatType || 'N/A';
            const action = ai.recommendedAction || inc.recommended_action || inc.recommendedAction || 'N/A';

            let formattedDate = 'N/A';
            if (rawTs) {
                // Handle both seconds, ISO strings, and milliseconds unix timestamps
                const ms = (typeof rawTs === 'number') ? (rawTs > 1e12 ? rawTs : rawTs * 1000) : Date.parse(rawTs);
                if (!isNaN(ms)) formattedDate = new Date(ms).toLocaleString();
            }

            return {
                id: inc.id || ai.incidentId,
                severity: severity,
                threatType: threatType,
                latitude: ai.latitude || inc.latitude || null,
                longitude: ai.longitude || inc.longitude || null,
                action: action,
                transcript: transcript,
                audioUrl: ai.audioUrl || inc.audioUrl || null,
                date: formattedDate,
                fullData: inc
            };
        });

        document.getElementById('totalIncidents').innerText = allIncidents.length;
        const emergencies = allIncidents.filter(i => {
            const s = i.severity.toLowerCase();
            return s === 'critical' || s === 'high' || s === 'emergency';
        }).length;
        document.getElementById('emergencyCount').innerText = emergencies;

        loader.style.display = 'none';
        renderTable(allIncidents);
    } catch (error) {
        console.error('Error fetching incidents:', error);
        loader.innerText = 'Error loading incidents. Check console for details.';
        loader.style.color = '#f85149';
    }
}

function renderTable(incidents) {
    const tbody = document.getElementById('incidentsBody');
    tbody.innerHTML = '';

    if (incidents.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-secondary);">No incidents found.</td></tr>';
        return;
    }

    // Sort by timestamp descending (newest first)
    incidents.sort((a, b) => {
        const tsA = a.fullData.ai_analysis?.timestamp || a.fullData.timestamp || 0;
        const tsB = b.fullData.ai_analysis?.timestamp || b.fullData.timestamp || 0;
        return tsB - tsA;
    });

    incidents.forEach(inc => {
        const severityClass = getSeverityClass(inc.severity);
        const locStr = inc.latitude && inc.longitude ?
            `<a href="https://maps.google.com/?q=${inc.latitude},${inc.longitude}" target="_blank" style="color:var(--accent-blue)">${inc.latitude.toFixed(4)}, ${inc.longitude.toFixed(4)}</a>`
            : '<span style="color:var(--text-secondary)">Unknown</span>';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${inc.id || 'N/A'}</strong></td>
            <td style="color:var(--text-secondary); font-size: 0.9rem;">${inc.date}</td>
            <td><span class="severity-pill ${severityClass}">${inc.severity}</span></td>
            <td>${inc.threatType}</td>
            <td>${locStr}</td>
            <td>${inc.action}</td>
            <td><div class="transcript-preview" title="${inc.transcript}">${inc.transcript}</div></td>
            <td>
                <button class="btn-view" onclick="viewDetails('${inc.id}')">View Details</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function getSeverityClass(severity) {
    if (!severity) return 'severity-low';
    const s = severity.toLowerCase();
    if (s.includes('critical') || s.includes('emergency')) return 'severity-critical';
    if (s.includes('high')) return 'severity-high';
    return 'severity-medium';
}

window.viewDetails = function (incidentId) {
    const incident = allIncidents.find(i => i.id === incidentId);
    if (!incident) return;

    const modal = document.getElementById('detailsModal');
    const modalBody = document.getElementById('modalBody');

    const analysis = incident.fullData.ai_analysis || incident.fullData;

    let html = `
        <div class="detail-grid">
            <div class="detail-item">
                <h4>Incident ID</h4>
                <p>${incident.id}</p>
            </div>
            <div class="detail-item">
                <h4>Recommended Action</h4>
                <p style="color:var(--accent-yellow)">${incident.action}</p>
            </div>
            <div class="detail-item">
                <h4>Threat Classification</h4>
                <p>${incident.threatType} (Conf: ${analysis.confidence != null ? (analysis.confidence * 100).toFixed(1) + '%' : 'N/A'})</p>
            </div>
            <div class="detail-item">
                <h4>Location</h4>
                <p>${incident.latitude ? `<a href="https://maps.google.com/?q=${incident.latitude},${incident.longitude}" target="_blank" style="color:var(--accent-blue)">${incident.latitude}, ${incident.longitude}</a>` : 'Not provided'}</p>
            </div>
            <div class="detail-item">
                <h4>Timestamp</h4>
                <p>${incident.date}</p>
            </div>
            <div class="detail-item">
                <h4>Emergency</h4>
                <p style="color:${analysis.is_emergency || analysis.isEmergency ? 'var(--accent-red)' : 'var(--accent-green)'}">${(analysis.is_emergency || analysis.isEmergency) ? '⚠ YES' : '✓ No'}</p>
            </div>
        </div>
        
        <div class="detail-item" style="margin-bottom: 1.5rem;">
            <h4>Analysis Summary</h4>
            <p style="font-size: 1rem; color: var(--text-primary);">${analysis.summary || 'No summary available.'}</p>
        </div>

        ${(analysis.audio_url || analysis.audioUrl || incident.audioUrl) ? `
        <div class="detail-item audio-section" style="margin-bottom: 1.5rem;">
            <h4>🔊 Audio Recording</h4>
            <audio controls preload="metadata" style="width: 100%; margin-top: 0.5rem;">
                <source src="${analysis.audio_url || analysis.audioUrl || incident.audioUrl}" type="audio/mp4">
                Your browser does not support the audio element.
            </audio>
        </div>` : ''}

        <div class="detail-item" style="margin-bottom: 1.5rem;">
            <h4>Full Transcript</h4>
            <p style="font-size: 0.95rem; font-style: italic; color: #c9d1d9;">"${incident.transcript}"</p>
        </div>

        <h4 style="color:var(--text-secondary); margin: 1.5rem 0 0.8rem;">AI Scores & Breakdown</h4>
        <div class="detail-grid">
            <div class="detail-item">
                <h4>Severity Score</h4>
                <p style="font-size: 1.4rem;">${(analysis.severity_score != null || analysis.severityScore != null || analysis.fusion_score != null) ? ((analysis.severity_score ?? analysis.severityScore ?? analysis.fusion_score) * 100).toFixed(0) + '%' : 'N/A'}</p>
            </div>
            <div class="detail-item">
                <h4>Final Severity Level</h4>
                <p><span class="severity-pill ${getSeverityClass(incident.severity)}">${incident.severity}</span></p>
            </div>
            <div class="detail-item">
                <h4>Stress Score</h4>
                <p style="font-size: 1.4rem;">${(analysis.stress_score != null || analysis.stressScore != null || analysis.stress_level != null) ? ((analysis.stress_score ?? analysis.stressScore ?? parseFloat(analysis.stress_level)) * 100).toFixed(0) + '%' : 'N/A'}</p>
            </div>
            <div class="detail-item">
                <h4>Intent</h4>
                <p>${analysis.intent || 'N/A'}</p>
            </div>
        </div>

        ${analysis.details ? `
        <h4 style="color:var(--text-secondary); margin: 1.5rem 0 0.8rem;">Processing Details</h4>
        <div class="detail-grid">
            ${analysis.details.processing_time_sec != null ? `
            <div class="detail-item">
                <h4>Processing Time</h4>
                <p>${analysis.details.processing_time_sec}s</p>
            </div>` : ''}
            ${analysis.details.emotion_details ? `
            <div class="detail-item">
                <h4>Avg Pitch</h4>
                <p>${analysis.details.emotion_details.avg_pitch_hz || 0} Hz</p>
            </div>
            <div class="detail-item">
                <h4>Avg Energy</h4>
                <p>${analysis.details.emotion_details.avg_energy || 0}</p>
            </div>
            <div class="detail-item">
                <h4>Stress Indicators</h4>
                <p>${(analysis.details.emotion_details.metrics && analysis.details.emotion_details.metrics.length > 0) ? analysis.details.emotion_details.metrics.join(', ') : 'None detected'}</p>
            </div>` : ''}
            ${analysis.details.fusion_breakdown ? `
            <div class="detail-item">
                <h4>Stress Contribution</h4>
                <p>${(analysis.details.fusion_breakdown.stress_contribution * 100).toFixed(0)}%</p>
            </div>
            <div class="detail-item">
                <h4>Threat Contribution</h4>
                <p>${(analysis.details.fusion_breakdown.threat_contribution * 100).toFixed(0)}%</p>
            </div>
            <div class="detail-item">
                <h4>Keyword Contribution</h4>
                <p>${(analysis.details.fusion_breakdown.keyword_contribution * 100).toFixed(0)}%</p>
            </div>` : ''}
        </div>` : ''}

        <div class="detail-item" style="margin-top: 1.5rem;">
            <h4>Model Version</h4>
            <p>${analysis.modelVersion || 'N/A'}</p>
        </div>
    `;

    modalBody.innerHTML = html;
    modal.style.display = "block";
}
