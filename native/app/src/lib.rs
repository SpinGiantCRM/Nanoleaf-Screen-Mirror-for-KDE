//! Native single-strip application. Python is used only as a test oracle.
pub mod analysis;
pub mod capture;
pub mod config;
pub mod device;
pub mod geometry;
mod highlight;
pub mod launcher;
pub mod onboarding;
pub mod package;
pub mod pipeline;
#[cfg(feature = "gui")]
pub mod portal_file;
pub mod prediction;
pub mod priority;
pub mod probe;
pub mod profile;
pub mod repeat;
pub mod response;
pub mod screens;
pub mod service;
mod session;
pub mod spatial;
pub mod tray;
#[cfg(feature = "gui")]
pub mod ui;
pub mod worker;
