# DocsFinder - Project Summary

## Overview
DocsFinder is a PyQt5-based desktop application that provides fast and efficient searching within document files. It supports searching across multiple document files simultaneously using parallel processing for improved performance.

## Project Structure

### Main Files
- `main.py` - Application entry point with initialization and loading screen management
- `requirements.txt` - Python dependencies

### Source Directory (`src/`)

#### Core Application Files
- `main_app.py` - Main application window and UI logic (ExcelSearchApp class)
- `config.py` - Configuration and warning suppression settings
- `constants.py` - Application constants and default values

#### UI Components
- `loading_dialog.py` - Loading screen with progress indicators
- `search_exception_dialog_improved.py` - Advanced search exception configuration dialog
- `ui_components.py` - Reusable UI components
- `sheet_viewer.py` - Excel sheet viewing and data display
- `result_model.py` - QAbstractItemModel for virtual-scrolling result tree (QTreeView)

#### Search and Processing
- `search_worker.py` - Parallel search worker threads
- `search_utils.py` - Search utilities and helper functions
- `streaming_search.py` - Streaming search implementation
- `file_processor.py` - File processing and Excel handling
- `excel_utils.py` - Excel file utilities and data extraction

#### Data Management
- `app_settings.py` - Application settings management
- `file_cache.py` - File caching for performance optimization

### Additional Directories
- `config/` - Configuration files storage
- `icon/` - Application icons and resources
- `build/` - Build output directory
- `docs/` - Documentation
- `logs/` - Application logs
- `venv/` - Python virtual environment

## Key Features

### Search Capabilities
- **Multi-file search**: Search across multiple Excel files (.xlsx, .xls, .xlsm)
- **Search modes**: Exact match or partial match searching
- **Case sensitivity**: Optional case-sensitive search via icon button
- **Parallel processing**: Configurable worker threads for fast processing
- **Smart filtering**: Exclude rows where 'Unused' header columns have value of 1
- **Always-active search**: Search button remains active, with validation on execution

### User Interface
- **Loading screen**: Progress indication during application startup
- **File management**: Add individual files or entire folders with simplified path display
- **Results display**: Clickable search results with detailed row data (no row numbers)
- **Exception handling**: Advanced search exception configuration via icon buttons
- **Settings persistence**: Saves user preferences and last used directories
- **Modern UI controls**: Icon-based buttons for case sensitivity, filtering, and settings
- **Selection feedback**: Real-time selection status display below file explorer

### Performance Optimizations
- **File caching**: Caches Excel data for faster subsequent searches
- **Memory management**: Efficient handling of large Excel files
- **Warning suppression**: Eliminates pandas and library warnings for cleaner output

## Technical Architecture

### Dependencies
- **PyQt5**: GUI framework (≥5.15.0)
- **pandas**: Data manipulation (≥1.0.0)
- **numpy**: Numerical operations (≥1.18.0)
- **xlrd**: Excel reading support (≥1.2.0)
- **openpyxl**: Modern Excel file support (≥3.0.0)
- **pyinstaller**: Executable building (≥4.0)

### Design Patterns
- **MVC Architecture**: Separation of UI, logic, and data
- **Worker Threads**: Non-blocking search operations
- **Caching Strategy**: File-based caching for performance
- **Settings Management**: Centralized configuration handling

## Build and Deployment

### Development Setup
1. Install Python 3.6+
2. Install dependencies: `pip install -r requirements.txt`
3. Run application: `python main.py`

### Executable Creation
- Use included build scripts for creating standalone executables
- Supports both single-file and directory distribution modes

## Key Classes and Components

### ExcelSearchApp (`main_app.py`)
- Main application window
- Handles user interactions and UI events
- Manages search operations and results display
- Integrates with all other components

### ParallelSearchWorker (`search_worker.py`)
- Implements threaded search operations
- Handles multiple Excel files simultaneously
- Reports progress and results back to UI

### LoadingDialog (`loading_dialog.py`)
- Displays application startup progress
- Provides user feedback during initialization
- Automatically closes when startup completes

### SearchExceptionDialogImproved (`search_exception_dialog_improved.py`)
- Advanced search filtering configuration
- Header-based exclusion rules
- Condition-based filtering options

## Development Notes

### Code Quality
- Warning suppression configured in `config.py`
- Optimized imports and initialization in `main.py`
- Removed all test files and duplicate code for production
- Consistent error handling throughout application

### Performance Considerations
- Uses multiprocessing for CPU-intensive operations
- Implements file caching to avoid re-reading Excel files
- Lazy loading of UI components
- Memory-efficient data handling

### Maintenance
- Settings are saved to `config/docs_finder_settings.txt`
- Logs are stored in `logs/` directory
- All user preferences persist between sessions
- Clear separation of concerns for easy maintenance

## Usage Workflow
1. Launch application (loading screen appears if needed)
2. Add Excel files or folders using UI buttons
3. Enter search term and select search mode
4. Configure parallel processing settings
5. Execute search operation
6. View results and click for detailed row data
7. Use search exceptions for advanced filtering

This application provides a robust, user-friendly solution for searching across Excel files with enterprise-level performance and features.