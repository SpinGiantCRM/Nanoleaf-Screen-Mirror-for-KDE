//! Native single-strip application. Python is used only as a test oracle.
pub mod capture;
pub mod config;
pub mod device;
pub mod geometry;
pub mod pipeline;
#[cfg(feature = "gui")]
pub mod ui;
