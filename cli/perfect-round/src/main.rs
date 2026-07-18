use std::collections::HashMap;
use std::fmt;
use std::path::PathBuf;
use std::str::FromStr;

use anyhow::{Context, Result, anyhow};
use clap::Parser;
use rand::SeedableRng;
use rand::rngs::StdRng;
use rand_distr::{Distribution, Normal};
use serde::Deserialize;

#[derive(Parser)]
#[command(name = "perfect-round")]
#[command(about = "Club-by-club shot plan built from your real dispersion data")]
struct Args {
    /// Course JSON file
    #[arg(default_value = "data/coyote-creek.json")]
    course: PathBuf,

    /// Bag JSON generated from the NeverMissTheGreen shot log
    #[arg(long, default_value = "data/bag.json")]
    bag: PathBuf,

    /// Tee set to play
    #[arg(long, default_value = "white")]
    tee: String,

    /// Monte Carlo samples per club decision
    #[arg(long, default_value_t = 2000)]
    sims: usize,

    /// Print the bag with raw vs reliability-adjusted spread
    #[arg(short, long)]
    verbose: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
enum Club {
    Driver,
    Wood(u8),
    Hybrid(u8),
    Iron(u8),
    Wedge(u8),
    Putter,
}

impl fmt::Display for Club {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Club::Driver => write!(f, "Driver"),
            Club::Wood(n) => write!(f, "{n}-Wood"),
            Club::Hybrid(n) => write!(f, "{n}-Hybrid"),
            Club::Iron(n) => write!(f, "{n}-Iron"),
            Club::Wedge(deg) => write!(f, "{deg}° Wedge"),
            Club::Putter => write!(f, "Putter"),
        }
    }
}

impl FromStr for Club {
    type Err = anyhow::Error;

    /// Parses shot-log club codes: driver, 3w, 3h, 4ir..9ir, pw, 50/54/58.
    fn from_str(code: &str) -> Result<Self> {
        Ok(match code {
            "driver" => Club::Driver,
            "pw" => Club::Wedge(46),
            _ => {
                if let Some(n) = code.strip_suffix("ir") {
                    Club::Iron(n.parse()?)
                } else if let Some(n) = code.strip_suffix('w') {
                    Club::Wood(n.parse()?)
                } else if let Some(n) = code.strip_suffix('h') {
                    Club::Hybrid(n.parse()?)
                } else {
                    Club::Wedge(
                        code.parse()
                            .map_err(|_| anyhow!("unknown club code {code:?}"))?,
                    )
                }
            }
        })
    }
}

struct ClubStats {
    club: Club,
    avg_dist: f64,
    std_dev_yds: f64, // short long — reliability-adjusted, see effective_spread
    raw_std_dev_yds: Option<f64>, // observed spread; None below 2 samples
    samples: u32,
    lateral_std_dev_yds: f64, // left right — hand-maintained in bag.json (no target line in the log)
}

struct Hole {
    number: u8,
    par: u8,
    distance_yds: u32,
}

struct Course {
    name: String,
    holes: Vec<Hole>,
}

// On-disk formats: the bag comes from scripts/fetch_bag.sh, courses are
// hand-entered scorecards with a yardage per tee set.

#[derive(Deserialize)]
struct BagFile {
    source: String,
    clubs: Vec<BagClub>,
}

#[derive(Deserialize)]
struct BagClub {
    club: String,
    avg_dist: f64,
    std_dev_yds: Option<f64>,
    samples: u32,
    #[serde(default)]
    lateral_std_dev_yds: f64,
}

/// Predictive spread for a club: blends the observed spread with a
/// distance-scaled prior, weighted by how many shots back it up, then
/// widens for the uncertainty of the average itself. Two shots with a
/// 3-yard spread end up wider than a hundred shots with a 10-yard one.
fn effective_spread(avg_dist: f64, raw_sd: Option<f64>, samples: u32) -> f64 {
    // The prior: typical amateur distance dispersion grows with club
    // length. It counts as PRIOR_WEIGHT pseudo-shots in the blend.
    const PRIOR_WEIGHT: f64 = 8.0;
    let prior_sd = (0.07 * avg_dist).max(5.0);

    let n = f64::from(samples.max(1));
    // Pool observed and prior variance; the observed side carries its
    // n-1 degrees of freedom, so thin data barely moves the prior.
    let df = n - 1.0;
    let observed_var = raw_sd.map_or(0.0, |s| s * s);
    let pooled_var =
        (df * observed_var + PRIOR_WEIGHT * prior_sd * prior_sd) / (df + PRIOR_WEIGHT);
    // Widen for the uncertain mean: Var[next shot] = sigma^2 * (1 + 1/n).
    (pooled_var * (1.0 + 1.0 / n)).sqrt()
}

#[derive(Deserialize)]
struct CourseFile {
    name: String,
    holes: Vec<HoleFile>,
}

#[derive(Deserialize)]
struct HoleFile {
    number: u8,
    par: u8,
    yds: HashMap<String, f64>,
}

/// Expected strokes for a mid-handicap amateur to hole out from `yds`
/// away, including short game and putting. Piecewise-linear over rough
/// Broadie-style anchors.
fn baseline(yds: f64) -> f64 {
    const ANCHORS: &[(f64, f64)] = &[
        (0.0, 1.5),
        (5.0, 2.25),
        (15.0, 2.5),
        (25.0, 2.6),
        (40.0, 2.7),
        (60.0, 2.8),
        (80.0, 2.9),
        (100.0, 2.95),
        (120.0, 3.0),
        (140.0, 3.1),
        (160.0, 3.2),
        (180.0, 3.35),
        (200.0, 3.5),
        (225.0, 3.65),
        (250.0, 3.8),
        (275.0, 3.95),
        (300.0, 4.1),
        (350.0, 4.4),
        (400.0, 4.7),
        (450.0, 5.0),
        (500.0, 5.3),
        (560.0, 5.65),
    ];
    let last = ANCHORS[ANCHORS.len() - 1];
    if yds >= last.0 {
        return last.1;
    }
    for w in ANCHORS.windows(2) {
        let (x0, y0) = w[0];
        let (x1, y1) = w[1];
        if yds <= x1 {
            return y0 + (y1 - y0) * (yds - x0) / (x1 - x0);
        }
    }
    last.1
}

/// A shot the engine may pick: a full swing with a bag club, or a
/// part-swing wedge scaled to the remaining distance.
struct Candidate {
    label: String,
    mean: f64,
    sd: f64,
    lateral_sd: f64,
}

/// Expected strokes to finish the hole if we hit this candidate now:
/// one stroke plus the baseline cost of wherever the ball ends up,
/// averaged over the club's 2D dispersion (long/short and left/right).
fn expected_strokes(cand: &Candidate, remaining: f64, sims: usize, rng: &mut StdRng) -> f64 {
    let carry_dist = Normal::new(cand.mean, cand.sd).expect("sd must be positive");
    let lateral_dist = Normal::new(0.0, cand.lateral_sd).expect("lateral sd must be non-negative");
    let total: f64 = (0..sims)
        .map(|_| {
            let carry = carry_dist.sample(rng).max(0.0);
            let lateral = lateral_dist.sample(rng);
            baseline((remaining - carry).hypot(lateral))
        })
        .sum();
    1.0 + total / sims as f64
}

fn candidates(bag: &[ClubStats], remaining: f64, is_tee_shot: bool) -> Vec<Candidate> {
    let mut cands: Vec<Candidate> = bag
        .iter()
        .filter(|c| c.club != Club::Putter)
        .filter(|c| is_tee_shot || c.club != Club::Driver)
        .map(|c| Candidate {
            label: c.club.to_string(),
            mean: c.avg_dist,
            sd: c.std_dev_yds,
            lateral_sd: c.lateral_std_dev_yds,
        })
        .collect();

    // Inside full-wedge range, allow a part-swing with the highest-lofted
    // club: aims at the pin, dispersion scales with swing length.
    let shortest = bag
        .iter()
        .filter(|c| c.club != Club::Putter)
        .min_by(|a, b| a.avg_dist.total_cmp(&b.avg_dist))
        .expect("bag must contain at least one full-swing club");
    if remaining < shortest.avg_dist {
        // Dispersion (both axes) scales down with the swing length.
        let swing = remaining / shortest.avg_dist;
        cands.push(Candidate {
            label: format!("{} part ({remaining:.0}y)", shortest.club),
            mean: remaining,
            sd: (0.10 * remaining).max(4.0),
            lateral_sd: shortest.lateral_std_dev_yds * swing,
        });
    }
    cands
}

struct HolePlan {
    route: Vec<String>,
    expected: f64,
}

fn recommend(hole: &Hole, bag: &[ClubStats], sims: usize, rng: &mut StdRng) -> HolePlan {
    let mut remaining = hole.distance_yds as f64;
    let mut route = Vec::new();
    // Expected strokes-to-finish of the most recent shot, from where it
    // was hit. It already prices that shot's dispersion plus everything
    // after it, so the hole estimate is (earlier shots) + this value.
    let mut last_e = baseline(remaining);

    // Plan full shots until we're green-side (baseline covers the rest);
    // advance by each chosen club's mean for the nominal route.
    while remaining > 30.0 && route.len() < 8 {
        let scored: Vec<(f64, Candidate)> = candidates(bag, remaining, route.is_empty())
            .into_iter()
            .map(|c| (expected_strokes(&c, remaining, sims, rng), c))
            .collect();
        let (e, best) = scored
            .into_iter()
            .min_by(|(ea, _), (eb, _)| ea.total_cmp(eb))
            .expect("candidate list is never empty");
        remaining = (remaining - best.mean).abs();
        route.push(best.label);
        last_e = e;
    }

    let expected = (route.len().saturating_sub(1)) as f64 + last_e;
    if remaining > 0.5 {
        route.push(format!("chip ({remaining:.0}y)"));
    }
    route.push(Club::Putter.to_string());
    HolePlan { route, expected }
}

fn main() -> Result<()> {
    let args = Args::parse();

    let bag_file: BagFile = serde_json::from_str(
        &std::fs::read_to_string(&args.bag)
            .with_context(|| format!("reading bag file {}", args.bag.display()))?,
    )
    .context("parsing bag JSON")?;
    let bag: Vec<ClubStats> = bag_file
        .clubs
        .iter()
        .map(|c| {
            Ok(ClubStats {
                club: c.club.parse()?,
                avg_dist: c.avg_dist,
                std_dev_yds: effective_spread(c.avg_dist, c.std_dev_yds, c.samples),
                raw_std_dev_yds: c.std_dev_yds,
                samples: c.samples,
                lateral_std_dev_yds: c.lateral_std_dev_yds,
            })
        })
        .collect::<Result<_>>()?;

    let course_file: CourseFile = serde_json::from_str(
        &std::fs::read_to_string(&args.course)
            .with_context(|| format!("reading course file {}", args.course.display()))?,
    )
    .context("parsing course JSON")?;
    let holes = course_file
        .holes
        .iter()
        .map(|h| {
            let yds = h
                .yds
                .get(&args.tee)
                .with_context(|| format!("hole {} has no {:?} tee", h.number, args.tee))?;
            Ok(Hole {
                number: h.number,
                par: h.par,
                distance_yds: *yds as u32,
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let course = Course {
        name: course_file.name,
        holes,
    };

    println!("Let's Golf!");
    println!("@ {} — {} tees", course.name, args.tee);
    let total_samples: u32 = bag_file.clubs.iter().map(|c| c.samples).sum();
    println!(
        "Bag: {} clubs fit from {} logged shots ({})\n",
        bag.len(),
        total_samples,
        bag_file.source
    );

    if args.verbose {
        println!(
            "{:<10} {:>3} {:>7} {:>8} {:>8} {:>8}",
            "Club", "n", "avg", "raw sd", "eff sd", "lateral"
        );
        for c in &bag {
            let raw = c
                .raw_std_dev_yds
                .map_or_else(|| "—".to_string(), |s| format!("{s:.1}"));
            println!(
                "{:<10} {:>3} {:>7.1} {:>8} {:>8.1} {:>8.1}",
                c.club.to_string(),
                c.samples,
                c.avg_dist,
                raw,
                c.std_dev_yds,
                c.lateral_std_dev_yds,
            );
        }
        println!();
    }

    // Seeded so repeated runs give the same plan.
    let mut rng = StdRng::seed_from_u64(42);

    let mut total_expected = 0.0;
    let mut total_par: u32 = 0;
    let mut nine_expected = 0.0;
    let mut nine_par: u32 = 0;

    for hole in &course.holes {
        let plan = recommend(hole, &bag, args.sims, &mut rng);
        println!(
            "Hole {:>2}  Par {}  {:>3} yds:  {}  (est. {:.1} strokes)",
            hole.number,
            hole.par,
            hole.distance_yds,
            plan.route.join(" → "),
            plan.expected,
        );

        total_expected += plan.expected;
        total_par += u32::from(hole.par);
        nine_expected += plan.expected;
        nine_par += u32::from(hole.par);
        if hole.number == 9 || hole.number as usize == course.holes.len() {
            let label = if hole.number == 9 { "Front 9" } else { "Back 9" };
            println!("         {label}: par {nine_par}, expected {nine_expected:.1}\n");
            nine_expected = 0.0;
            nine_par = 0;
        }
    }

    println!(
        "TOTAL: par {}, expected {:.1} ({:+.1})",
        total_par,
        total_expected,
        total_expected - f64::from(total_par)
    );
    Ok(())
}
