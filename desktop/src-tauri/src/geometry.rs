#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}
#[cfg(test)]
pub fn recover(saved: Option<Rect>, monitors: &[Rect]) -> Rect {
    recover_scaled(saved, monitors, 1.)
}
/// Physical work-area coordinates, so mixed DPI screens do not reinterpret pixels.
pub fn recover_scaled(saved: Option<Rect>, monitors: &[Rect], scale: f64) -> Rect {
    let scale = if scale.is_finite() && scale > 0. {
        scale
    } else {
        1.
    };
    let fallback = Rect {
        x: 0.,
        y: 0.,
        width: 1280.,
        height: 800.,
    };
    let valid = |r: &Rect| {
        [r.x, r.y, r.width, r.height].iter().all(|v| v.is_finite()) && r.width > 0. && r.height > 0.
    };
    let screens: Vec<_> = monitors.iter().filter(|m| valid(m)).collect();
    let first = screens.first().copied().unwrap_or(&fallback);
    let prior = saved.filter(valid);
    let screen = prior
        .and_then(|r| {
            screens
                .iter()
                .copied()
                .find(|m| r.x >= m.x && r.x < m.x + m.width && r.y >= m.y && r.y < m.y + m.height)
        })
        .unwrap_or(first);
    let r = prior.unwrap_or(Rect {
        x: screen.x + 24.,
        y: screen.y + 24.,
        width: 420. * scale,
        height: 620. * scale,
    });
    let width = r.width.max(320. * scale).min(screen.width);
    let height = r.height.max(280. * scale).min(screen.height);
    Rect {
        x: r.x.clamp(screen.x, screen.x + screen.width - width),
        y: r.y.clamp(screen.y, screen.y + screen.height - height),
        width,
        height,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn monitor() -> Rect {
        Rect {
            x: 0.,
            y: 25.,
            width: 1440.,
            height: 875.,
        }
    }
    #[test]
    fn missing_defaults_fit_screen() {
        let r = recover(None, &[monitor()]);
        assert_eq!(r.width, 420.);
        assert_eq!(r.height, 620.);
        assert!(r.y >= 25.);
    }
    #[test]
    fn offscreen_recovers() {
        let r = recover(
            Some(Rect {
                x: 9000.,
                y: -9000.,
                width: 420.,
                height: 620.,
            }),
            &[monitor()],
        );
        assert!(r.x >= 0. && r.x + r.width <= 1440.);
        assert!(r.y >= 25.);
    }
    #[test]
    fn oversized_and_corrupt_recover() {
        for width in [1e12, -10., f64::NAN, f64::INFINITY] {
            let r = recover(
                Some(Rect {
                    x: f64::NAN,
                    y: 0.,
                    width,
                    height: 1e12,
                }),
                &[monitor()],
            );
            assert!(r.width.is_finite() && r.width > 0. && r.width <= 1440.);
            assert!(r.x.is_finite() && r.height <= 875.);
        }
    }
    #[test]
    fn negative_monitor_preserved() {
        let r = Rect {
            x: -1100.,
            y: 80.,
            width: 450.,
            height: 600.,
        };
        assert_eq!(
            recover(
                Some(r),
                &[
                    monitor(),
                    Rect {
                        x: -1280.,
                        y: 0.,
                        width: 1280.,
                        height: 1024.
                    }
                ]
            ),
            r
        );
    }
    #[test]
    fn small_screen_fits() {
        let m = Rect {
            x: 0.,
            y: 0.,
            width: 300.,
            height: 250.,
        };
        let r = recover(None, &[m]);
        assert!(r.width <= m.width && r.height <= m.height);
    }
    #[test]
    fn no_monitors_has_safe_fallback() {
        assert!(recover(None, &[]).width > 0.);
    }
    #[test]
    fn retina_defaults_keep_logical_size() {
        let r = recover_scaled(
            None,
            &[Rect {
                x: 0.,
                y: 50.,
                width: 3024.,
                height: 1850.,
            }],
            2.,
        );
        assert_eq!(r.width, 840.);
        assert_eq!(r.height, 1240.);
    }
    #[test]
    fn corrupt_json_is_not_geometry() {
        assert!(serde_json::from_str::<Rect>(r#"{"x":"no"}"#).is_err());
    }
}
