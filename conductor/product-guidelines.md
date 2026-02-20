# NBA DFS Optimizer Product Guidelines

## Prose Style
- **Technical/Formal:** Use precise, technical terminology. Documentation and UI labels should be objective and concise. Avoid conversational filler or overly simplified analogies.
- **Accuracy First:** Ensure all data labels and metrics (e.g., "Geomean Ownership," "Projected Points") are clearly defined and consistently used across the application.

## UI Branding & Design
- **Data-Dense/Professional:** The interface should prioritize data density and professional utility. Use large, sortable tables and clear charts for visualizing lineup distributions and exposures.
- **Focus on Information:** Minimize decorative elements. Every visual component should serve a functional purpose in analyzing or building lineups.

## User Experience (UX) Principles
- **Reliability:** The core optimization logic must be robust. Results should be reproducible, and all constraints should be strictly enforced to ensure valid DraftKings entries.
- **Speed:** Optimize for high-performance execution. The system should minimize the time from data upload to exported lineups, even when handling large generation pools.

## Feedback & Communication
- **Live Progress Bars:** Provide real-time feedback during long-running tasks like solver execution or ranker processing. 
- **Clear Milestone Indicators:** Use status bars and progress indicators to show the user exactly where the system is in the optimization pipeline.
