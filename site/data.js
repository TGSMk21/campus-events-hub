/* Seed data for the concept demo. Dates are relative to today so the demo never goes stale. */
window.SEED = (function () {
  'use strict';
  function at(days, hour, mins) {
    var d = new Date();
    d.setHours(hour, mins || 0, 0, 0);
    d.setDate(d.getDate() + days);
    return d.toISOString();
  }
  function plus(iso, hours) { return new Date(new Date(iso).getTime() + hours * 3600e3).toISOString(); }

  var users = {
    student: { id: 1, name: 'Hamusonde Muntanga', email: 'student@mu.ac.zm', role: 'student', phone: '+260971234567', whatsapp: true, interests: ['academic', 'sports'] },
    organizer: { id: 2, name: 'Lushomo Lungo', email: 'organizer@mu.ac.zm', role: 'organizer', phone: '', whatsapp: false, interests: ['career'] },
    admin: { id: 3, name: 'Student Affairs Office', email: 'admin@mu.ac.zm', role: 'admin', phone: '', whatsapp: false, interests: [] }
  };

  var venues = [
    { id: 1, name: 'Main Auditorium', capacity: 400, location: 'Block A', facilities: ['projector', 'sound', 'stage'] },
    { id: 2, name: 'Lecture Hall A', capacity: 150, location: 'School of Engineering & Technology', facilities: ['projector'] },
    { id: 3, name: 'Sports Ground', capacity: 800, location: 'Behind the hostels', facilities: ['floodlights'] },
    { id: 4, name: 'Student Centre', capacity: 120, location: 'Next to the cafeteria', facilities: ['sound', 'kitchen'] },
    { id: 5, name: 'ICT Lab 3', capacity: 60, location: 'SET building, 2nd floor', facilities: ['computers', 'projector'] }
  ];

  var groups = [
    { slug: 'cs-society', name: 'Computer Science Society', category: 'academic', followers: 86, meets: 'Thursdays 17:00, ICT Lab 3', description: 'Talks, hackathons and study sessions for anyone interested in software, data and systems.' },
    { slug: 'football', name: 'MU Football Club', category: 'sports', followers: 140, meets: 'Tue & Fri 16:00, Sports Ground', description: "Men's and women's teams. Training is open to all levels; inter-university fixtures every month." },
    { slug: 'drama', name: 'Drama & Arts Collective', category: 'cultural', followers: 64, meets: 'Wednesdays 18:00, Student Centre', description: 'Theatre, poetry and music nights. Two productions a year and regular open-mic evenings.' },
    { slug: 'chess', name: 'Chess Club', category: 'club', followers: 31, meets: 'Mondays 17:30, Library foyer', description: 'Casual games, puzzles and a termly tournament. Boards provided.' },
    { slug: 'careers', name: 'Careers & Alumni Network', category: 'career', followers: 112, meets: 'Monthly, see events', description: 'CV clinics, mock interviews and meet-the-employer sessions with alumni.' },
    { slug: 'green', name: 'Green Campus Initiative', category: 'club', followers: 45, meets: 'Saturdays 08:00', description: 'Tree planting, clean-ups and sustainability projects on campus.' }
  ];

  var list = [
    // id, group, title, category, venue, days, hour, hours, capacity, priceK, sold, description
    [1, 'cs-society', 'ICT461 Web Engineering Showcase', 'academic', 1, 3, 14, 3, 300, 0, 212, 'Student teams demo their web platforms: real-time apps, secure APIs and accessible interfaces. Judges from industry.'],
    [2, 'cs-society', '24-Hour Campus Hackathon', 'academic', 5, 9, 9, 10, 60, 0, 48, 'Build something useful for campus life in teams of four. Food, mentors and prizes provided. Bring a laptop.'],
    [3, 'football', 'Inter-University Football Derby', 'sports', 3, 5, 15, 2, 800, 10, 530, 'Mulungushi vs. Copperbelt University. Come in university colours. Gates open an hour before kick-off.'],
    [4, 'drama', 'Mr & Mrs IT Pageant', 'cultural', 1, 12, 18, 4, 350, 25, 297, "The School of Technology's annual pageant: talent, fashion and a lot of laughter."],
    [5, 'drama', 'Open Mic Poetry Night', 'cultural', 4, 2, 18, 2, 100, 0, 37, 'Share a poem, a song or a story, or just come to listen. Sign-up sheet at the door from 17:30.'],
    [6, 'chess', 'Termly Chess Tournament', 'club', 4, 7, 9, 6, 64, 5, 60, 'Swiss-system, 7 rounds, 15+10 time control. Beginners section available. Trophies for the top three.'],
    [7, 'careers', 'Tech Careers Fair 2026', 'career', 1, 15, 9, 6, 400, 0, 154, 'Meet employers from banking, telecoms and start-ups. Bring printed CVs; the CV clinic runs all morning.'],
    [8, 'careers', 'CV & LinkedIn Clinic', 'career', 2, 4, 10, 2, 80, 0, 79, 'One-to-one CV reviews with alumni recruiters, plus a talk on writing a LinkedIn profile that gets noticed.'],
    [9, 'green', 'Campus Tree Planting Day', 'club', 3, 6, 8, 3, 200, 0, 41, "We're planting 300 indigenous trees along the main road. Gloves and tools provided."],
    [10, null, 'Mental Health & Wellness Talk', 'academic', 2, 8, 16, 2, 150, 0, 66, 'The counselling unit on managing exam stress, sleep and burnout, with an anonymous Q&A at the end.']
  ];

  var events = [], bookings = [];
  list.forEach(function (r) {
    var starts = at(r[5], r[6]);
    events.push({ id: r[0], group: r[1], title: r[2], category: r[3], venueId: r[4], startsAt: starts, endsAt: plus(starts, r[7]),
      capacity: r[8], price: r[9], sold: r[10], description: r[11], status: 'published', organizerId: 2 });
    bookings.push({ id: r[0], eventId: r[0], venueId: r[4], startsAt: starts, endsAt: plus(starts, r[7]), attendance: r[8],
      requirements: ['sound'], status: 'approved', note: '', documents: ['approval-letter.pdf'] });
  });

  // A pending request that clashes with the showcase (same venue, overlapping time): the admin sees the conflict.
  var clash = at(3, 15);
  events.push({ id: 11, group: 'chess', title: 'Chess Simul Exhibition', category: 'club', venueId: 1, startsAt: clash, endsAt: plus(clash, 2),
    capacity: 120, price: 0, sold: 0, description: 'A grandmaster plays 30 students at once. Spectators welcome; players must register.', status: 'pending', organizerId: 2 });
  bookings.push({ id: 11, eventId: 11, venueId: 1, startsAt: clash, endsAt: plus(clash, 2), attendance: 120, requirements: ['projector'], status: 'pending', note: '', documents: [] });
  // A pending request without a clash.
  var git = at(20, 10);
  events.push({ id: 12, group: 'cs-society', title: 'Intro to Git & GitHub Workshop', category: 'academic', venueId: 5, startsAt: git, endsAt: plus(git, 3),
    capacity: 60, price: 0, sold: 0, description: 'Hands-on: branches, pull requests and merge conflicts. Bring a laptop with Git installed.', status: 'pending', organizerId: 2 });
  bookings.push({ id: 12, eventId: 12, venueId: 5, startsAt: git, endsAt: plus(git, 3), attendance: 50, requirements: ['projector'], status: 'pending', note: '', documents: ['faculty-approval.pdf'] });
  // A draft.
  var robo = at(25, 14);
  events.push({ id: 13, group: null, title: 'Robotics Club Launch', category: 'club', venueId: 2, startsAt: robo, endsAt: plus(robo, 2),
    capacity: 100, price: 0, sold: 0, description: 'Meet the team building our entry for the national robotics challenge.', status: 'draft', organizerId: 2 });

  return {
    users: users, venues: venues, groups: groups, events: events, bookings: bookings,
    follows: ['cs-society', 'football'], tickets: [], notifications: [], chat: {},
    nextId: 100
  };
})();
