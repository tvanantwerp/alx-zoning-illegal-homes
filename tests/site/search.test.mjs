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
  const list = ["415 1/2 PRINCE ST", "1 A PRINCE ST", "607A PRINCE ST", "415 PRINCE ST", "2 PRINCE ST"];
  const found = findAddresses(list, "Prince").map(m => list[m.index]);
  assert.deepEqual(found, ["1 A PRINCE ST", "2 PRINCE ST", "415 1/2 PRINCE ST", "415 PRINCE ST", "607A PRINCE ST"]);
});

test("nothing found, and blank queries find nothing", () => {
  assert.deepEqual(findAddresses(ADDRESSES, "999 Nowhere Ln"), []);
  assert.deepEqual(findAddresses(ADDRESSES, "   "), []);
});

test("lots that share an address are listed once", () => {
  const found = findAddresses(["1 KING ST", "1 KING ST", "10 KING ST"], "King");
  assert.deepEqual(found.map(m => m.index), [0, 2]);
});
