import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeAddress, findAddresses } from "../../site/search.js";

const ADDRESSES = [
  "702 PRINCE ST",
  "415 PRINCE ST",
  "1102 PRINCESS ST UNIT 1100",
  "316 PRINCE ST UNIT 1",
  "1625 PRINCE ST",
  "115 A S SAINT ASAPH ST UNIT C-0A",
  "2121 JAMIESON AVE UNIT 809",
  "3401 MOUNT VERNON AVE",
  "415 PRINCESS ST",
  "100 OLD PRINCE RD",
];

test("spelled-out suffixes and directions match the short forms", () => {
  assert.equal(normalizeAddress("415 Prince Street"), "415 PRINCE ST");
  assert.equal(normalizeAddress("2121 Jamieson Avenue, Apt. 809"), "2121 JAMIESON AVE UNIT 809");
  assert.equal(normalizeAddress("2121 Jamieson Ave #809"), "2121 JAMIESON AVE UNIT 809");
  assert.equal(normalizeAddress("115 A South St. Asaph Street"), normalizeAddress("115 A S SAINT ASAPH ST"));
  assert.equal(normalizeAddress("3401 Mt Vernon Av"), normalizeAddress("3401 MOUNT VERNON AVE"));
  assert.equal(normalizeAddress("  12   north  fayette   st "), "12 N FAYETTE ST");
});

test("both spellings of an address find the same single lot", () => {
  assert.deepEqual(findAddresses(ADDRESSES, "415 Prince Street").map(m => m.index), [1]);
  assert.deepEqual(findAddresses(ADDRESSES, "415 PRINCE ST").map(m => m.index), [1]);
  assert.equal(findAddresses(ADDRESSES, "415 Prince Street")[0].exact, true);
});

test("a street name alone lists every lot on it, whole-word matches first", () => {
  const found = findAddresses(ADDRESSES, "Prince").map(m => ADDRESSES[m.index]);
  assert.deepEqual(found, [
    "100 OLD PRINCE RD", "415 PRINCE ST", "702 PRINCE ST", "1625 PRINCE ST", "316 PRINCE ST UNIT 1",
    "415 PRINCESS ST", "1102 PRINCESS ST UNIT 1100",
  ]);
});

test("a house number prefix matches only the lots that start with it", () => {
  const found = findAddresses(ADDRESSES, "415 prince").map(m => ADDRESSES[m.index]);
  assert.deepEqual(found, ["415 PRINCE ST", "415 PRINCESS ST"]);
});

test("halves and letters after the house number sort with the number", () => {
  const list = ["415 1/2 PRINCE ST", "1 A PRINCE ST", "607A PRINCE ST", "415 PRINCE ST", "2 PRINCE ST", "500 3/4 PRINCE ST"];
  const found = findAddresses(list, "Prince").map(m => list[m.index]);
  assert.deepEqual(found, ["1 A PRINCE ST", "2 PRINCE ST", "415 1/2 PRINCE ST", "415 PRINCE ST", "500 3/4 PRINCE ST", "607A PRINCE ST"]);
});

test("nothing found, and blank queries find nothing", () => {
  assert.deepEqual(findAddresses(ADDRESSES, "999 Nowhere Ln"), []);
  assert.deepEqual(findAddresses(ADDRESSES, "   "), []);
});

test("lots that share an address are listed once", () => {
  const found = findAddresses(["1 KING ST", "1 KING ST", "10 KING ST"], "King");
  assert.deepEqual(found.map(m => m.index), [0, 2]);
});

test("north and south sides of a street sort as separate streets", () => {
  const list = ["111 S UNION ST", "105 N UNION ST", "300S UNION ST", "115 A S UNION ST", "106 N UNION ST", "4 A N UNION ST"];
  const found = findAddresses(list, "Union").map(m => list[m.index]);
  assert.deepEqual(found, ["4 A N UNION ST", "105 N UNION ST", "106 N UNION ST", "111 S UNION ST", "115 A S UNION ST", "300S UNION ST"]);
  const west = ["101 S WEST ST", "431 A N WEST ST", "101 N WEST ST"];
  assert.deepEqual(findAddresses(west, "West").map(m => west[m.index]), ["101 N WEST ST", "431 A N WEST ST", "101 S WEST ST"]);
});

test("a half glued to the house number is split off", () => {
  assert.equal(normalizeAddress("1001/2 DUKE ST"), "100 1/2 DUKE ST");
  assert.equal(normalizeAddress("300S UNION ST"), "300 S UNION ST");
  const list = ["1001/2 DUKE ST", "100 DUKE ST", "99 DUKE ST"];
  assert.deepEqual(findAddresses(list, "1/2 duke").map(m => list[m.index]), ["1001/2 DUKE ST"]);
  assert.deepEqual(findAddresses(list, "100 1/2 duke").map(m => list[m.index]), ["1001/2 DUKE ST"]);
  assert.deepEqual(findAddresses(list, "Duke").map(m => list[m.index]), ["99 DUKE ST", "1001/2 DUKE ST", "100 DUKE ST"]);
});

test("a direction word typed alone finds streets named for it", () => {
  const list = ["780 N WEST ST", "602 WEST VIEW TER", "100 W GLEBE RD", "5 WESTMINSTER PL", "9 WILKES ST"];
  const found = findAddresses(list, "West").map(m => list[m.index]);
  assert.deepEqual(found, ["780 N WEST ST", "602 WEST VIEW TER", "5 WESTMINSTER PL"]);
});

test("lots sharing an address list each preferred lot, or else just one", () => {
  const list = ["1 KING ST", "1 KING ST", "1 KING ST", "2 KING ST", "2 KING ST"];
  const preferred = index => index === 1 || index === 2;
  const found = findAddresses(list, "King", undefined, preferred);
  assert.deepEqual(found.map(m => m.index), [1, 2, 3]);
});
