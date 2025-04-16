document.addEventListener('DOMContentLoaded', () => {

const downloadBtn = document.getElementById('downloadBtn');
const spinner = document.getElementById('spinner');
const apiKeyContainer = document.getElementById('apiKeyContainer');
const apiKeyInput = document.getElementById('apiKeyInput');

// Toggle API key input visibility based on fetch method
document.querySelectorAll('input[name="fetchMethod"]').forEach(radio => {
  radio.addEventListener('change', () => {
    const selected = document.querySelector('input[name="fetchMethod"]:checked').value;
    if (selected === 'youtube-api') {
      apiKeyContainer.style.display = 'block';
    } else {
      apiKeyContainer.style.display = 'none';
    }
  });
});

downloadBtn.addEventListener('click', async () => {
  const channelUrl = document.getElementById('channelUrl').value.trim();
  const outputDir = document.getElementById('outputDir').value.trim();
  const resultDiv = document.getElementById('result');
  const downloadLink = document.getElementById('downloadCsvBtn');

  // Get selected output option
  const outputOption = document.querySelector('input[name="outputOption"]:checked').value;

  // Get selected export fields
  const selectedFields = Array.from(document.querySelectorAll('input[name="exportField"]:checked'))
                              .map(cb => cb.value);

  // Get selected search type
  const searchType = document.querySelector('input[name="searchType"]:checked').value;

  // Hide download button initially
  downloadLink.style.display = 'none';
  downloadLink.href = '#';

  if (!channelUrl) {
    resultDiv.textContent = 'Please provide the YouTube channel URL.';
    return;
  }
  if (outputOption === 'save' && !outputDir) {
    resultDiv.textContent = 'Please provide the output directory when saving to folder.';
    return;
  }
  if (selectedFields.length === 0) {
    resultDiv.textContent = 'Please select at least one export field.';
    return;
  }

  // Show loading animation and disable button
  spinner.style.display = 'block';
  downloadBtn.disabled = true;
  resultDiv.innerHTML = `
    <div style="text-align: center;">
      <div class="spinner"></div>
      <p style="font-size: 1.2rem; color: #60a5fa; margin-top: 1rem;">Analyzing Channel</p>
      <p style="color: #94a3b8; margin-top: 0.5rem;">
        <span class="loading-dots">Fetching video data</span>
      </p>
    </div>
  `;
  
  // Add loading dots animation
  let dotCount = 0;
  const loadingInterval = setInterval(() => {
    const loadingSpan = document.querySelector('.loading-dots');
    if (loadingSpan) {
      dotCount = (dotCount + 1) % 4;
      loadingSpan.textContent = 'Fetching video data' + '.'.repeat(dotCount);
    } else {
      clearInterval(loadingInterval);
    }
  }, 500);

  try {
    // Step 1: Fetch video IDs
    const idsResponse = await fetch('/get_video_ids', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_url: channelUrl })
    });

    if (!idsResponse.ok) {
      const errorText = await idsResponse.text();
      resultDiv.textContent = 'Failed to get video IDs: ' + errorText;
      return;
    }

    const idsData = await idsResponse.json();
    const videoIds = idsData.video_ids || [];

    if (videoIds.length === 0) {
      resultDiv.textContent = 'No videos found on this channel.';
      return;
    }

    resultDiv.innerHTML = `
      <div style="text-align: center; margin-bottom: 1rem;">
        <p style="font-size: 1.2rem; color: #60a5fa;">Found ${videoIds.length} videos!</p>
        <p style="color: #94a3b8;">Fetching metadata in batches...</p>
      </div>
    `;

    const batchSize = 50;
    const batches = [];
    for (let i = 0; i < videoIds.length; i += batchSize) {
      batches.push(videoIds.slice(i, i + batchSize));
    }

    let allVideos = [];
    for (let b = 0; b < batches.length; b++) {
      const batch = batches[b];
      const progress = Math.round((b + 1) / batches.length * 100);
      
      resultDiv.innerHTML = `
        <div style="text-align: center;">
          <p style="font-size: 1.2rem; color: #60a5fa;">Processing Videos...</p>
          <p style="color: #94a3b8;">Batch ${b + 1} of ${batches.length}</p>
          <div style="margin: 1rem auto; width: 200px; height: 6px; background: #1e293b; border-radius: 3px; overflow: hidden;">
            <div style="width: ${progress}%; height: 100%; background: linear-gradient(90deg, #3b82f6, #60a5fa); transition: width 0.3s ease;"></div>
          </div>
          <p style="color: #94a3b8;">${progress}% Complete</p>
        </div>
      `;

      const metaResponse = await fetch('/get_metadata_api', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_ids: batch,
          export_fields: selectedFields
        })
      });

      if (!metaResponse.ok) {
        const errorText = await metaResponse.text();
        resultDiv.textContent += `Batch ${b + 1} failed: ${errorText}\n`;
        continue;
      }

      const metaData = await metaResponse.json();
      const videos = metaData.videos || [];
      allVideos = allVideos.concat(videos);
    }

    resultDiv.textContent += `Fetched metadata for ${allVideos.length} videos.\n`;

    if (allVideos.length === 0) {
      resultDiv.textContent += `No accessible videos found. They may be private, deleted, or region-restricted.\n`;
      downloadLink.style.display = "none";
    } else {
      // Send request to save/download file on server
      const saveResponse = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_url: channelUrl,
          output_dir: outputDir,
          output_option: outputOption,
          export_fields: selectedFields,
          search_type: searchType
        })
      });

      if (!saveResponse.ok) {
        const errorText = await saveResponse.text();
        resultDiv.textContent = 'Failed to save/download file: ' + errorText;
        return;
      }

      const saveData = await saveResponse.json();
      
      console.log('Save response:', saveData); // Debug log

      if (!saveData.csv_path) {
        console.error('No CSV path in response:', saveData); // Debug log
        resultDiv.textContent = "Error: No file path returned from server";
        downloadLink.style.display = "none";
        return;
      }

      if (outputOption === 'save') {
        // Show success message with animation for save mode
        resultDiv.classList.add('success-animation');
        resultDiv.innerHTML = `
          <div style="text-align: center;">
            <p style="font-size: 1.2rem; margin-bottom: 1rem;">✅ File saved successfully!</p>
            <p style="color: #94a3b8; margin-bottom: 0.5rem;">${saveData.message}</p>
            <p style="color: #60a5fa; font-family: monospace; padding: 0.5rem; background: #1e293b; border-radius: 0.25rem; display: inline-block;">
              ${saveData.csv_path}
            </p>
          </div>
        `;
        
        // Remove animation class after it completes
        setTimeout(() => {
          resultDiv.classList.remove('success-animation');
        }, 500);
      } else {
        // For download mode, trigger immediate download
        const downloadUrl = `/download_csv?path=${encodeURIComponent(saveData.csv_path)}`;
        console.log('Download URL:', downloadUrl); // Debug log
        
        // Create a temporary link and click it
        const tempLink = document.createElement('a');
        tempLink.href = downloadUrl;
        tempLink.download = `youtube_videos_${Date.now()}.csv`;
        document.body.appendChild(tempLink);
        tempLink.click();
        document.body.removeChild(tempLink);
        
        // Show success message with animation
        resultDiv.classList.add('success-animation');
        resultDiv.innerHTML = `
          <div style="text-align: center;">
            <p style="font-size: 1.2rem; margin-bottom: 1rem;">✨ Download started! ✨</p>
            <p style="color: #94a3b8;">Your file will be saved to your downloads folder.</p>
          </div>
        `;
        
        // Remove animation class after it completes
        setTimeout(() => {
          resultDiv.classList.remove('success-animation');
        }, 500);
      }
    }

  } catch (error) {
    console.error('Error:', error);
    resultDiv.innerHTML = `
      <div style="text-align: center; padding: 1rem; background: #450a0a; border: 1px solid #dc2626; border-radius: 0.5rem;">
        <p style="color: #fee2e2; font-size: 1.1rem; margin-bottom: 0.5rem;">⚠️ Error Occurred</p>
        <p style="color: #fca5a5; font-family: monospace; background: #991b1b; padding: 0.5rem; border-radius: 0.25rem; margin-top: 0.5rem;">
          ${error.message}
        </p>
        <p style="color: #fee2e2; font-size: 0.9rem; margin-top: 1rem;">
          Please try again. If the problem persists, try using a different channel URL or export option.
        </p>
      </div>
    `;
  } finally {
    spinner.style.display = 'none';
    downloadBtn.disabled = false;
    downloadBtn.textContent = '🚀 Get Video List';
  }
});

// Dynamically enable/disable export fields based on search type
const searchTypeRadios = document.querySelectorAll('input[name="searchType"]');
const exportFieldCheckboxes = document.querySelectorAll('input[name="exportField"]');
const exportFieldsSection = document.getElementById('exportFieldsSection');

function updateExportFieldsVisibility() {
  const selectedType = document.querySelector('input[name="searchType"]:checked').value;
  const advancedFieldsDiv = document.getElementById('advancedFields');
  if (selectedType === 'basic') {
    advancedFieldsDiv.style.display = 'none';
    exportFieldCheckboxes.forEach(cb => {
      if (['Title', 'URL', 'ID'].includes(cb.value)) {
        cb.disabled = false;
      } else {
        cb.checked = false;
        cb.disabled = true;
      }
    });
  } else {
    advancedFieldsDiv.style.display = 'block';
    exportFieldCheckboxes.forEach(cb => {
      cb.disabled = false;
    });
  }
}

searchTypeRadios.forEach(radio => {
  radio.addEventListener('change', () => {
    updateExportFieldsVisibility();
  });
});

// Handle output option changes
function updateOutputDirVisibility() {
  const outputOption = document.querySelector('input[name="outputOption"]:checked').value;
  const saveDirSection = document.getElementById('saveDirSection');
  
  if (outputOption === 'save') {
    saveDirSection.classList.remove('hidden');
    document.getElementById('outputDir').setAttribute('required', 'required');
  } else {
    saveDirSection.classList.add('hidden');
    document.getElementById('outputDir').removeAttribute('required');
  }
}

// Initialize visibility states on page load
updateExportFieldsVisibility();
updateOutputDirVisibility();

// Add listeners for output option changes
document.querySelectorAll('input[name="outputOption"]').forEach(radio => {
  radio.addEventListener('change', updateOutputDirVisibility);
});

document.getElementById('browseBtn').addEventListener('click', async () => {
  try {
    const response = await fetch('/select_folder');
    if (!response.ok) {
      console.error('Failed to open folder dialog');
      return;
    }
    const data = await response.json();
    if (data.path) {
      document.getElementById('outputDir').value = data.path;
    }
  } catch (error) {
    console.error('Error selecting folder:', error);
  }
});

});
